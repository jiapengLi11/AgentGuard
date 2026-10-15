"""Reproduce a small, labelled rule-detector smoke evaluation; not Agent ASR."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway-python/src"))

from sujie_gateway.detection import DETECTOR_VERSION, detect_indirect  # noqa: E402
from sujie_gateway.m1_runtime import new_id  # noqa: E402

DATASET = ROOT / "eval/cases/detection_v1.json"


def evaluate() -> dict:
    raw = DATASET.read_bytes()
    dataset = json.loads(raw)
    outcomes = []
    confusion = {"tp": 0, "fn": 0, "fp": 0, "tn": 0}
    seen: set[str] = set()
    for item in dataset["cases"]:
        case_id = item["id"]
        if case_id in seen or not isinstance(item["attack"], bool):
            raise ValueError("INVALID_EVAL_CASE")
        seen.add(case_id)
        text = "benign log entry. " * item.get("prefix_repeat", 0) + item["text"]
        _, finding = detect_indirect(text, new_id(), new_id())
        detected = finding is not None
        key = (
            "tp"
            if item["attack"] and detected
            else "fn"
            if item["attack"]
            else "fp"
            if detected
            else "tn"
        )
        confusion[key] += 1
        outcomes.append(
            {
                "id": case_id,
                "family": item["family"],
                "attack": item["attack"],
                "detected": detected,
                "outcome": key.upper(),
            }
        )
    attacks, clean = confusion["tp"] + confusion["fn"], confusion["fp"] + confusion["tn"]
    return {
        "dataset_id": dataset["dataset_id"],
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "evaluation_scope": "rule_detector_only_not_agent_asr",
        "detector_version": DETECTOR_VERSION,
        "case_count": len(outcomes),
        "confusion": confusion,
        "attack_recall": confusion["tp"] / attacks if attacks else None,
        "clean_false_positive_rate": confusion["fp"] / clean if clean else None,
        "cases": outcomes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, help="write a JSON report to this path")
    args = parser.parse_args()
    result = evaluate()
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, "utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
