"""Validate matching local-mapping runs before comparing their observed effects."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_injecagent_local import summarize

BINDINGS = (
    "model",
    "host_version",
    "prompt_sha256",
    "source_manifest_sha256",
    "tool_catalog_sha256",
    "dataset_sha256",
    "base_user_tasks",
    "attack_intents",
    "repeats",
)
CASE_BINDINGS = (
    "pair_id",
    "attack",
    "user_tool",
    "private_tool",
    "upstream_index",
    "source_identity_sha256",
    "response_sha256",
)


def compare(reports: list[dict]) -> dict:
    if not reports:
        raise ValueError("MISSING_LOCAL_REPORTS")
    reference = reports[0]
    rows, modes = [], []
    for report in reports:
        if report.get("kind") != "injecagent-sealed-local-mapping-execution" or any(
            report.get(key) != reference.get(key) for key in BINDINGS
        ):
            raise ValueError("LOCAL_REPORT_CONFIGURATION_MISMATCH")
        if (
            not isinstance(report.get("modes"), list)
            or len(set(report["modes"])) != len(report["modes"])
            or any(
                mode in modes or mode not in {"unsafe", "full", "full-recovery", "full-projection"}
                for mode in report["modes"]
            )
        ):
            raise ValueError("DUPLICATE_LOCAL_MODE")
        modes.extend(report["modes"])
        rows.extend(report["cases"])
    keyed = {}
    for row in rows:
        key = (row["mode"], row["repeat"], row["id"])
        if key in keyed or row["mode"] not in modes:
            raise ValueError("DUPLICATE_LOCAL_CASE")
        keyed[key] = row
    keys_by_mode = {
        mode: {(row["repeat"], row["id"]) for row in rows if row["mode"] == mode} for mode in modes
    }
    expected = reference["base_user_tasks"] * reference["attack_intents"] * 2 * reference["repeats"]
    if any(len(keys) != expected for keys in keys_by_mode.values()) or any(
        keys != keys_by_mode[modes[0]] for keys in keys_by_mode.values()
    ):
        raise ValueError("INCOMPLETE_LOCAL_PAIRED_RUN")
    for repeat, case_id in keys_by_mode[modes[0]]:
        baseline = keyed[modes[0], repeat, case_id]
        if any(
            keyed[mode, repeat, case_id].get(field) != baseline.get(field)
            for mode in modes
            for field in CASE_BINDINGS
        ):
            raise ValueError("LOCAL_CASE_BINDING_MISMATCH")
    summary = summarize(rows, modes)
    return {
        "kind": "injecagent-local-mapping-comparison",
        **{key: reference[key] for key in BINDINGS},
        "modes": modes,
        "summary": summary,
        "task_summary": {
            mode: {
                user_tool: {
                    "attack_completed": sum(
                        row["task_completed"]
                        for row in rows
                        if row["mode"] == mode and row["user_tool"] == user_tool and row["attack"]
                    ),
                    "attack_cases": sum(
                        row["mode"] == mode and row["user_tool"] == user_tool and row["attack"]
                        for row in rows
                    ),
                    "clean_completed": sum(
                        row["task_completed"]
                        for row in rows
                        if row["mode"] == mode
                        and row["user_tool"] == user_tool
                        and not row["attack"]
                    ),
                }
                for user_tool in sorted({row["user_tool"] for row in rows})
            }
            for mode in modes
        },
        "claims": "Sealed local mapping with synthetic private data, one model trajectory per configuration; no official InjecAgent ASR or generalization claim.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = compare([json.loads(path.read_text("utf-8")) for path in args.reports])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
