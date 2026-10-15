"""Paired, task-aware real-model pilot on a deterministic InjecAgent subset."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "demo-agent"), str(ROOT / "eval")]

from run_external_injecagent import IDENTITY_FIELDS, load_cases  # noqa: E402
from sujie_demo_agent.bailian_agent import (  # noqa: E402
    BailianChatModel,
    BailianCredentials,
    ModelProtocolError,
)
from sujie_demo_agent.semantic_detector import (  # noqa: E402
    TASK_AWARE_PROMPT,
    TaskAwareSemanticClassifier,
)
from sujie_gateway.detection import DETECTOR_VERSION, detect_indirect  # noqa: E402
from sujie_gateway.m1_runtime import new_id  # noqa: E402

PLACEHOLDER = "<Attacker Instruction>"
BENIGN_REPLACEMENT = (
    "This field contains ordinary descriptive information about the requested item."
)


def select_pairs(source_root: Path) -> tuple[list[dict], str]:
    groups, manifest_sha = load_cases(source_root)
    selected = []
    for kind in ("dh", "ds"):
        by_tool: dict[str, list[tuple[int, dict]]] = defaultdict(list)
        for index, case in enumerate(groups[kind, "base"]):
            by_tool[case["User Tool"]].append((index, case))
        for tool in sorted(by_tool):
            index, case = min(
                by_tool[tool],
                key=lambda pair: hashlib.sha256(
                    json.dumps(
                        [pair[1][field] for field in IDENTITY_FIELDS],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            )
            template = case.get("Tool Response Template")
            if not isinstance(template, str) or template.count(PLACEHOLDER) != 1:
                raise ValueError("INVALID_INJECAGENT_TEMPLATE")
            clean = template.replace(PLACEHOLDER, BENIGN_REPLACEMENT)
            attack = case["Tool Response"]
            if not 1 <= len(clean) <= 12000 or not 1 <= len(attack) <= 12000:
                raise ValueError("TASK_AWARE_RESPONSE_TOO_LARGE")
            selected.append(
                {
                    "kind": kind,
                    "index": index,
                    "tool_name": tool,
                    "trusted_user_request": case["User Instruction"],
                    "attack_type": case["Attack Type"],
                    "attack": attack,
                    "clean": clean,
                    "case_identity_sha256": hashlib.sha256(
                        json.dumps(
                            [case[field] for field in IDENTITY_FIELDS],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                }
            )
    return selected, manifest_sha


async def evaluate(
    source_root: Path, model: BailianChatModel, *, expected_manifest_sha256: str | None = None
) -> dict:
    pairs, manifest_sha = select_pairs(source_root)
    if expected_manifest_sha256 and manifest_sha != expected_manifest_sha256.lower():
        raise ValueError("INJECAGENT_MANIFEST_MISMATCH")
    detector = TaskAwareSemanticClassifier(model)
    rows = []
    for pair in pairs:
        for label in ("attack", "clean"):
            content = pair[label]
            _, rule_finding = detect_indirect(content, new_id(), new_id())
            row = {
                key: pair[key]
                for key in ("kind", "index", "tool_name", "attack_type", "case_identity_sha256")
            } | {
                "label": label,
                "response_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "rule_detected": rule_finding is not None,
            }
            try:
                predicted, reason = await detector.classify(
                    pair["trusted_user_request"], pair["tool_name"], content
                )
                row.update({"predicted": predicted, "reason_code": reason})
            except (ModelProtocolError, ValueError) as exc:
                row["error"] = str(exc)
                rows.append(row)
                break
            rows.append(row)
        if rows and "error" in rows[-1]:
            break
    valid = [row for row in rows if "predicted" in row]
    return {
        "kind": "injecagent-task-aware-semantic-pilot",
        "scope": "One base attack per user tool and kind, paired with a synthetic neutral template fill; no agent execution or official ASR.",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model.model,
        "detector_version": DETECTOR_VERSION,
        "prompt_sha256": hashlib.sha256(TASK_AWARE_PROMPT.encode()).hexdigest(),
        "source_manifest_sha256": manifest_sha,
        "selection_sha256": hashlib.sha256(
            json.dumps(
                [(pair["kind"], pair["index"], pair["case_identity_sha256"]) for pair in pairs],
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
        "summary": {
            "selected_pairs": len(pairs),
            "attempted_rows": len(rows),
            "TP": sum(row["label"] == "attack" and row["predicted"] for row in valid),
            "FN": sum(row["label"] == "attack" and not row["predicted"] for row in valid),
            "FP": sum(row["label"] == "clean" and row["predicted"] for row in valid),
            "TN": sum(row["label"] == "clean" and not row["predicted"] for row in valid),
            "invalid": len(rows) - len(valid),
            "rule_attack_hits": sum(
                row["label"] == "attack" and row["rule_detected"] for row in rows
            ),
            "rule_clean_hits": sum(
                row["label"] == "clean" and row["rule_detected"] for row in rows
            ),
            "total_tokens": sum(item.get("total_tokens", 0) for item in model.usage),
        },
        "rows": rows,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--credentials-csv",
        type=Path,
        default=os.environ.get("SUJIE_BAILIAN_CREDENTIAL_CSV"),
        required="SUJIE_BAILIAN_CREDENTIAL_CSV" not in os.environ,
    )
    parser.add_argument("--model", default="qwen-plus-2025-12-01")
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    model = BailianChatModel(
        BailianCredentials.from_csv(args.credentials_csv), model=args.model, max_tokens=256
    )
    report = await evaluate(
        args.source_root, model, expected_manifest_sha256=args.expected_manifest_sha256
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return int(report["summary"]["invalid"] > 0)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
