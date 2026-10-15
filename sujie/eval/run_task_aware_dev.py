"""Pin and compare v1/v2 on development data; all calls are durably recorded."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "demo-agent")]

from sujie_demo_agent.bailian_agent import (  # noqa: E402
    BailianChatModel,
    BailianCredentials,
    ModelProtocolError,
)
from sujie_demo_agent.semantic_detector import (  # noqa: E402
    TASK_AWARE_PROMPT,
    TaskAwareSemanticClassifier,
)
from sujie_demo_agent.semantic_detector_v2 import (  # noqa: E402
    TASK_AWARE_V2_PROMPT,
    TaskAwareSemanticClassifierV2,
)

MODEL = "qwen-plus-2025-12-01"
FILES = (
    "demo-agent/sujie_demo_agent/semantic_detector.py",
    "demo-agent/sujie_demo_agent/semantic_detector_v2.py",
    "demo-agent/sujie_demo_agent/bailian_agent.py",
    "eval/run_task_aware_dev.py",
    "eval/build_task_aware_dev.py",
    "eval/benign_documents.py",
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_dataset(path: Path) -> dict:
    dataset = json.loads(path.read_bytes())
    if dataset.get("kind") != "task-aware-development-suite-v2":
        raise ValueError("INVALID_DATASET")
    rows = dataset.get("rows")
    if not isinstance(rows, list) or not rows or len(rows) > 150:
        raise ValueError("INVALID_DATASET_ROWS")
    seen = set()
    for row in rows:
        if (
            row["id"] in seen
            or type(row["expected"]) is not bool
            or row["response_sha256"] != digest(row["untrusted_tool_response"].encode())
            or any(
                not isinstance(row[key], str) or not 1 <= len(row[key]) <= limit
                for key, limit in (
                    ("trusted_user_request", 4096),
                    ("tool_name", 128),
                    ("untrusted_tool_response", 12000),
                )
            )
            or ("partition" in row and row["partition"] != "train")
        ):
            raise ValueError("INVALID_DATASET_ROW")
        seen.add(row["id"])
    return dataset


def freeze(dataset_path: Path) -> dict:
    dataset = load_dataset(dataset_path)
    return {
        "kind": "task-aware-development-comparison-v2",
        "model": MODEL,
        "max_tokens": 256,
        "temperature": 0,
        "model_tools": [],
        "dataset_sha256": digest(dataset_path.read_bytes()),
        "source_manifest_sha256": dataset["source_manifest_sha256"],
        "prompt_sha256": {
            "v1": digest(TASK_AWARE_PROMPT.encode()),
            "v2": digest(TASK_AWARE_V2_PROMPT.encode()),
        },
        "implementation_sha256": {name: digest((ROOT / name).read_bytes()) for name in FILES},
        "planned_requests": len(dataset["rows"]) * 2,
        "order": "Dataset row order; v1/v2 order alternates by response SHA parity; one call per row per variant, no retries.",
        "scope": dataset["scope"],
    }


def metrics(rows: list[dict]) -> dict:
    valid = [r for r in rows if type(r.get("predicted")) is bool]
    return {
        "attempted": len(rows),
        "valid": len(valid),
        "invalid_or_pending": len(rows) - len(valid),
        "TP": sum(r["expected"] and r["predicted"] for r in valid),
        "FN": sum(r["expected"] and not r["predicted"] for r in valid),
        "FP": sum(not r["expected"] and r["predicted"] for r in valid),
        "TN": sum(not r["expected"] and not r["predicted"] for r in valid),
        "returned_total_tokens": sum(r.get("usage", {}).get("total_tokens", 0) for r in rows),
        "rows_with_usage": sum("total_tokens" in r.get("usage", {}) for r in rows),
    }


def summarize(rows: list[dict], planned: int) -> dict:
    result = {v: metrics([r for r in rows if r["variant"] == v]) for v in ("v1", "v2")}
    result["strata"] = {
        source: {
            v: metrics([r for r in rows if r["variant"] == v and r["source_type"] == source])
            for v in ("v1", "v2")
        }
        for source in sorted({r["source_type"] for r in rows})
    }
    result["attack_kinds"] = {
        kind: {
            v: metrics(
                [r for r in rows if r["variant"] == v and r.get("kind") == kind and r["expected"]]
            )
            for v in ("v1", "v2")
        }
        for kind in ("dh", "ds")
    }
    result["planned_requests"] = planned
    result["unattempted"] = planned - len(rows)
    result["complete"] = sum(result[v]["valid"] for v in ("v1", "v2")) == planned
    return result


def save(path: Path, report: dict, planned: int) -> None:
    report["summary"] = summarize(report["rows"], planned)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    temporary.replace(path)


async def evaluate(dataset: dict, protocol: dict, protocol_sha: str, model, out: Path) -> dict:
    if out.exists():
        raise ValueError("REPORT_ALREADY_EXISTS")
    if model.model != protocol["model"] or model.max_tokens != protocol["max_tokens"]:
        raise ValueError("MODEL_MISMATCH")
    out.parent.mkdir(parents=True, exist_ok=True)
    classifiers = {
        "v1": TaskAwareSemanticClassifier(model),
        "v2": TaskAwareSemanticClassifierV2(model),
    }
    report = {
        "kind": "task-aware-development-comparison-v2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model.model,
        "protocol_sha256": protocol_sha,
        "source_manifest_sha256": protocol["source_manifest_sha256"],
        "scope": protocol["scope"],
        "rows": [],
    }
    planned = protocol["planned_requests"]
    save(out, report, planned)
    for selected in dataset["rows"]:
        order = ("v1", "v2") if int(selected["response_sha256"][-1], 16) % 2 == 0 else ("v2", "v1")
        for variant in order:
            row = {
                key: value
                for key, value in selected.items()
                if key not in ("trusted_user_request", "untrusted_tool_response", "execution")
            }
            row.update({"variant": variant, "status": "REQUESTED"})
            report["rows"].append(row)
            save(out, report, planned)
            started = time.perf_counter()
            before = len(getattr(model, "usage", []))
            try:
                predicted, reason = await classifiers[variant].classify(
                    selected["trusted_user_request"],
                    selected["tool_name"],
                    selected["untrusted_tool_response"],
                )
            except (ModelProtocolError, ValueError) as error:
                code = str(error)
                if not re.fullmatch(
                    r"BAILIAN_HTTP_[0-9]{3}|BAILIAN_TRANSPORT_ERROR|BAILIAN_RESPONSE_INVALID|TASK_AWARE_JSON_INVALID|INVALID_TASK_AWARE_INPUT",
                    code,
                ):
                    code = "CLASSIFIER_FAILED"
                row.update(
                    {
                        "status": "ERROR",
                        "error": code,
                        "model_wait_ms": round((time.perf_counter() - started) * 1000, 3),
                    }
                )
                returned = getattr(model, "usage", [])[before:]
                if len(returned) == 1:
                    row["usage"] = returned[0]
                save(out, report, planned)
                return report
            row.update(
                {
                    "status": "COMPLETE",
                    "predicted": predicted,
                    "reason_code": reason,
                    "model_wait_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            )
            returned = getattr(model, "usage", [])[before:]
            if len(returned) == 1:
                row["usage"] = returned[0]
            save(out, report, planned)
            if len(report["rows"]) % 10 == 0:
                print(
                    json.dumps({"completed": len(report["rows"]), "planned": planned}), flush=True
                )
    return report


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--expected-protocol-sha256")
    parser.add_argument("--credentials-csv", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    actual = freeze(args.dataset)
    if args.freeze:
        if args.protocol.exists():
            parser.error("PROTOCOL_ALREADY_EXISTS")
        args.protocol.parent.mkdir(parents=True, exist_ok=True)
        args.protocol.write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(
            json.dumps(
                {
                    "protocol_sha256": digest(args.protocol.read_bytes()),
                    "planned_requests": actual["planned_requests"],
                }
            )
        )
        return 0
    if not args.out or not args.credentials_csv or not args.expected_protocol_sha256:
        parser.error("EXECUTION_REQUIRES_OUT_CREDENTIALS_AND_PROTOCOL_HASH")
    raw = args.protocol.read_bytes()
    if digest(raw) != args.expected_protocol_sha256.lower() or json.loads(raw) != actual:
        parser.error("FROZEN_PROTOCOL_MISMATCH")
    model = BailianChatModel(
        BailianCredentials.from_csv(args.credentials_csv), model=MODEL, max_tokens=256
    )
    report = await evaluate(load_dataset(args.dataset), actual, digest(raw), model, args.out)
    print(json.dumps(report["summary"], ensure_ascii=False))
    return int(not report["summary"]["complete"])


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
