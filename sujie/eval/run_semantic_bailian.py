"""No-tool semantic detector evaluation on paired synthetic evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "demo-agent"), str(ROOT / "eval")]

from run_bailian import load_cases  # noqa: E402
from sujie_demo_agent.bailian_agent import (  # noqa: E402
    BailianChatModel,
    BailianCredentials,
    ModelProtocolError,
)
from sujie_demo_agent.semantic_detector import (  # noqa: E402
    DETECTOR_PROMPT,
    NoToolSemanticClassifier,
)


def detector_cases(suite: str) -> tuple[list[dict], str]:
    if suite in {"paired-v1", "scenario-v1"}:
        return load_cases(suite)
    if suite != "detection-v1":
        raise ValueError("UNKNOWN_DETECTOR_SUITE")
    data = json.loads((ROOT / "eval/cases/detection_v1.json").read_text("utf-8"))
    cases = []
    for item in data["cases"]:
        case = dict(item)
        repeat = case.pop("prefix_repeat", 0)
        if not isinstance(repeat, int) or not 0 <= repeat <= 500:
            raise ValueError("INVALID_DETECTION_SUITE")
        case["text"] = "日志：连接核查中。\n" * repeat + case["text"]
        cases.append(case)
    return cases, data["dataset_id"]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--credentials-csv",
        type=Path,
        default=os.environ.get("SUJIE_BAILIAN_CREDENTIAL_CSV"),
        required="SUJIE_BAILIAN_CREDENTIAL_CSV" not in os.environ,
    )
    parser.add_argument("--model", default="qwen-plus-2025-12-01")
    parser.add_argument(
        "--suite",
        choices=["paired-v1", "detection-v1", "scenario-v1"],
        default="paired-v1",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    cases, dataset_id = detector_cases(args.suite)
    model = BailianChatModel(
        BailianCredentials.from_csv(Path(args.credentials_csv)), model=args.model, max_tokens=256
    )
    detector = NoToolSemanticClassifier(model)
    rows = []
    for case in cases:
        try:
            predicted, reason = await detector.classify(case["text"])
            rows.append(
                {
                    "id": case["id"],
                    "family": case["family"],
                    "attack": case["attack"],
                    "predicted": predicted,
                    "reason_code": reason,
                }
            )
        except ModelProtocolError as exc:
            rows.append({"id": case["id"], "attack": case["attack"], "error": str(exc)})
    valid = [row for row in rows if "predicted" in row]
    tp = sum(row["attack"] and row["predicted"] for row in valid)
    fn = sum(row["attack"] and not row["predicted"] for row in valid)
    fp = sum(not row["attack"] and row["predicted"] for row in valid)
    tn = sum(not row["attack"] and not row["predicted"] for row in valid)
    report = {
        "kind": "semantic-detector-no-tool-synthetic-evaluation",
        "model": model.model,
        "dataset_id": dataset_id,
        "dataset_sha256": hashlib.sha256(
            json.dumps(cases, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "prompt_sha256": hashlib.sha256(DETECTOR_PROMPT.encode()).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "summary": {
            "TP": tp,
            "FN": fn,
            "FP": fp,
            "TN": tn,
            "invalid": len(rows) - len(valid),
            "total_tokens": sum(item.get("total_tokens", 0) for item in model.usage),
        },
        "claims": "Offline synthetic classifier only; it is not on the gateway hot path.",
    }
    output = args.out or ROOT / f"eval/reports/runs/bailian_semantic_{args.suite}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"summary": report["summary"], "output": str(output)}, ensure_ascii=False))
    return 1 if report["summary"]["invalid"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
