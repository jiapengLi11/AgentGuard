"""Freeze disjoint attacker-intent and user-tool partitions before model tuning."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from run_external_injecagent import load_cases  # noqa: E402

SPLITS = ("train", "validation", "test")


def _assign(values: set[str]) -> dict[str, str]:
    ordered = sorted(values, key=lambda value: hashlib.sha256(value.encode()).hexdigest())
    train_end = len(ordered) * 60 // 100
    validation_end = train_end + len(ordered) * 20 // 100
    return {
        value: "train" if index < train_end else "validation" if index < validation_end else "test"
        for index, value in enumerate(ordered)
    }


def build_split(source_root: Path) -> dict:
    groups, manifest_sha = load_cases(source_root)
    base = {kind: groups[kind, "base"] for kind in ("dh", "ds")}
    tools = {row["User Tool"] for rows in base.values() for row in rows}
    tool_assignment = _assign(tools)
    intent_assignment = {
        kind: _assign({row["Attacker Instruction"] for row in rows}) for kind, rows in base.items()
    }
    rows = []
    for kind in ("dh", "ds"):
        for index, case in enumerate(base[kind]):
            intent_split = intent_assignment[kind][case["Attacker Instruction"]]
            tool_split = tool_assignment[case["User Tool"]]
            partition = intent_split if intent_split == tool_split else "cross_holdout"
            rows.append(
                {
                    "kind": kind,
                    "index": index,
                    "case_identity_sha256": hashlib.sha256(
                        json.dumps(
                            [
                                case["User Instruction"],
                                case["Attacker Instruction"],
                                case["Attack Type"],
                                case["User Tool"],
                            ],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest(),
                    "intent_sha256": hashlib.sha256(
                        case["Attacker Instruction"].encode()
                    ).hexdigest(),
                    "tool_sha256": hashlib.sha256(case["User Tool"].encode()).hexdigest(),
                    "intent_split": intent_split,
                    "tool_split": tool_split,
                    "partition": partition,
                }
            )
    counts = Counter(row["partition"] for row in rows)
    return {
        "kind": "injecagent-disjoint-intent-tool-split",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_manifest_sha256": manifest_sha,
        "algorithm": "SHA-256 sort; 60/20/20 train/validation/test separately by attack intent within dh/ds and by user tool; only diagonal pairs enter a partition.",
        "summary": {
            "base_cases": len(rows),
            "attacker_intents": {kind: len(intent_assignment[kind]) for kind in ("dh", "ds")},
            "user_tools": len(tool_assignment),
            "partition_counts": {name: counts[name] for name in (*SPLITS, "cross_holdout")},
        },
        "rows": rows,
    }


def mark_pilot_exposure(report: dict, pilot: dict) -> None:
    """Annotate a previously frozen split without changing its assignments."""
    if pilot.get("source_manifest_sha256") != report["source_manifest_sha256"]:
        raise ValueError("PILOT_SOURCE_MISMATCH")
    known = {(row["kind"], row["index"], row["case_identity_sha256"]) for row in report["rows"]}
    if pilot.get("kind") == "injecagent-sealed-local-mapping-execution":
        exposed = {
            ("ds", row["upstream_index"], row["source_identity_sha256"])
            for row in pilot.get("cases", [])
        }
    else:
        exposed = {
            (row["kind"], row["index"], row["case_identity_sha256"])
            for row in pilot.get("rows", [])
        }
    if not exposed or not exposed <= known:
        raise ValueError("PILOT_SELECTION_MISMATCH")
    exposed |= {
        (row["kind"], row["index"], row["case_identity_sha256"])
        for row in report["rows"]
        if row.get("pilot_exposed")
    }
    for row in report["rows"]:
        row["pilot_exposed"] = (row["kind"], row["index"], row["case_identity_sha256"]) in exposed
    report["summary"]["pilot_exposed_counts"] = {
        name: sum(row["partition"] == name and row["pilot_exposed"] for row in report["rows"])
        for name in (*SPLITS, "cross_holdout")
    }
    report["summary"]["untouched_partition_counts"] = {
        name: report["summary"]["partition_counts"][name]
        - report["summary"]["pilot_exposed_counts"][name]
        for name in (*SPLITS, "cross_holdout")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--pilot-report", type=Path)
    parser.add_argument("--exposure-reports", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = build_split(args.source_root)
    if (
        args.expected_manifest_sha256
        and report["source_manifest_sha256"] != args.expected_manifest_sha256.lower()
    ):
        raise ValueError("INJECAGENT_MANIFEST_MISMATCH")
    if args.pilot_report:
        mark_pilot_exposure(report, json.loads(args.pilot_report.read_text("utf-8")))
    for path in args.exposure_reports or []:
        mark_pilot_exposure(report, json.loads(path.read_text("utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
