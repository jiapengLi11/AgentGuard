"""Execute a pinned classification partition, saving every attempted API request."""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "demo-agent")]

from sujie_demo_agent.bailian_agent import (  # noqa: E402
    BailianChatModel,
    BailianCredentials,
    ModelProtocolError,
)
from sujie_demo_agent.semantic_detector import TaskAwareSemanticClassifier  # noqa: E402
from sujie_gateway.detection import detect_indirect  # noqa: E402
from sujie_gateway.m1_runtime import new_id  # noqa: E402
from task_aware_protocol import MAX_TOKENS, MODEL, digest, selected_pairs  # noqa: E402


def summary(rows: list[dict], count: int, usage: list[dict]) -> dict:
    valid = [row for row in rows if type(row.get("predicted")) is bool]
    return {
        "planned_pairs": count,
        "planned_requests": count * 2,
        "attempted_rows": len(rows),
        "valid_rows": len(valid),
        "invalid_or_pending": len(rows) - len(valid),
        "unattempted_rows": count * 2 - len(rows),
        "TP": sum(row["label"] == "attack" and row["predicted"] for row in valid),
        "FN": sum(row["label"] == "attack" and not row["predicted"] for row in valid),
        "FP": sum(row["label"] == "clean" and row["predicted"] for row in valid),
        "TN": sum(row["label"] == "clean" and not row["predicted"] for row in valid),
        "rule_attack_hits": sum(row["label"] == "attack" and row["rule_detected"] for row in rows),
        "rule_attack_denominator": sum(row["label"] == "attack" for row in rows),
        "rule_clean_hits": sum(row["label"] == "clean" and row["rule_detected"] for row in rows),
        "rule_clean_denominator": sum(row["label"] == "clean" for row in rows),
        "total_tokens": sum(item.get("total_tokens", 0) for item in usage),
        "complete": len(valid) == count * 2,
    }


def save(out: Path, report: dict, count: int, model) -> None:
    report["summary"] = summary(report["rows"], count, getattr(model, "usage", []))
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    temporary.replace(out)


async def evaluate(
    protocol: dict, protocol_sha: str, partition: str, source_root: Path, model, out: Path
) -> dict:
    if out.exists():
        raise ValueError("REPORT_ALREADY_EXISTS")
    pairs = selected_pairs(protocol, source_root, partition)
    if model.model != protocol["model"] or model.max_tokens != protocol["max_tokens"]:
        raise ValueError("MODEL_PROTOCOL_MISMATCH")
    classifier = TaskAwareSemanticClassifier(model)
    report = {
        "kind": "injecagent-task-aware-frozen-classification",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model.model,
        "protocol_sha256": protocol_sha,
        "partition": partition,
        "source_manifest_sha256": protocol["source_manifest_sha256"],
        "scope": protocol["scope"],
        "control_type": protocol["control_type"],
        "rows": [],
    }
    save(out, report, len(pairs), model)
    for selected in pairs:
        for label in ("attack", "clean"):
            content = selected[label]
            _, finding = detect_indirect(content, new_id(), new_id())
            row = {
                key: selected[key]
                for key in ("kind", "index", "case_identity_sha256", "tool_name", "attack_type")
            }
            row.update(
                {
                    "label": label,
                    "response_sha256": digest(content.encode()),
                    "rule_detected": finding is not None,
                    "status": "REQUESTED",
                }
            )
            report["rows"].append(row)
            save(out, report, len(pairs), model)
            try:
                predicted, reason = await classifier.classify(
                    selected["trusted_user_request"], selected["tool_name"], content
                )
            except (ModelProtocolError, ValueError) as error:
                code = str(error)
                if not re.fullmatch(
                    r"(?:BAILIAN_HTTP_[0-9]{3}|BAILIAN_TRANSPORT_ERROR|BAILIAN_RESPONSE_INVALID|TASK_AWARE_JSON_INVALID|INVALID_TASK_AWARE_INPUT)",
                    code,
                ):
                    code = "CLASSIFIER_FAILED"
                row.update({"status": "ERROR", "error": code})
                save(out, report, len(pairs), model)
                return report
            row.update({"status": "COMPLETE", "predicted": predicted, "reason_code": reason})
            save(out, report, len(pairs), model)
    return report


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--expected-protocol-sha256", required=True)
    parser.add_argument("--partition", choices=("validation", "test"), required=True)
    parser.add_argument("--credentials-csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.protocol.read_bytes()
    protocol_sha = digest(raw)
    if protocol_sha != args.expected_protocol_sha256.lower():
        parser.error("PROTOCOL_HASH_MISMATCH")
    protocol = json.loads(raw)
    selected_pairs(protocol, args.source_root, args.partition)
    model = BailianChatModel(
        BailianCredentials.from_csv(args.credentials_csv), model=MODEL, max_tokens=MAX_TOKENS
    )
    report = await evaluate(
        protocol, protocol_sha, args.partition, args.source_root, model, args.out
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    return int(not report["summary"]["complete"])


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
