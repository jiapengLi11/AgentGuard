"""Compare matched authorized-transfer Full and no-provenance runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def compare(full: dict, ablated: dict) -> dict:
    keys = ("model", "dataset_id", "dataset_sha256", "host_version")
    if (
        full.get("mode") != "full"
        or ablated.get("mode") != "no-provenance"
        or any(full.get(key) != ablated.get(key) for key in keys)
    ):
        raise ValueError("INCOMPARABLE_CONFIGURATIONS")
    f_cases = {item["id"]: item for item in full["cases"]}
    a_cases = {item["id"]: item for item in ablated["cases"]}
    if (
        f_cases.keys() != a_cases.keys()
        or len(f_cases) != len(full["cases"])
        or len(a_cases) != len(ablated["cases"])
    ):
        raise ValueError("UNPAIRED_RUNS")
    rows = []
    for identifier, f in f_cases.items():
        a = a_cases[identifier]
        if (
            "error" in f
            or "error" in a
            or any(f[key] != a[key] for key in ("attack", "pair_id", "case_sha256"))
        ):
            raise ValueError("MISMATCHED_CASE")
        rows.append(
            {
                "id": identifier,
                "pair_id": f["pair_id"],
                "attack": f["attack"],
                "family": f["family"],
                "full_leak": f["honeytoken_leaked"],
                "ablated_leak": a["honeytoken_leaked"],
                "full_task_completed": f["task_completed"],
                "ablated_task_completed": a["task_completed"],
                "full_provenance_blocks": f["provenance_blocks"],
                "ablated_provenance_blocks": a["provenance_blocks"],
                "full_ask_decisions": f["ask_decisions"],
                "ablated_ask_decisions": a["ask_decisions"],
            }
        )
    attack = [row for row in rows if row["attack"]]
    control = [row for row in rows if not row["attack"]]
    return {
        "kind": "paired-synthetic-authorized-transfer-provenance-ablation",
        "model": full["model"],
        "dataset_id": full["dataset_id"],
        "dataset_sha256": full["dataset_sha256"],
        "rows": rows,
        "summary": {
            "attack_denominator": len(attack),
            "control_denominator": len(control),
            "full_attack_leaks": sum(row["full_leak"] for row in attack),
            "ablated_attack_leaks": sum(row["ablated_leak"] for row in attack),
            "full_control_leaks": sum(row["full_leak"] for row in control),
            "ablated_control_leaks": sum(row["ablated_leak"] for row in control),
            "full_attack_tasks_completed": sum(row["full_task_completed"] for row in attack),
            "ablated_attack_tasks_completed": sum(row["ablated_task_completed"] for row in attack),
            "full_control_tasks_completed": sum(row["full_task_completed"] for row in control),
            "ablated_control_tasks_completed": sum(
                row["ablated_task_completed"] for row in control
            ),
            "full_provenance_blocks": sum(row["full_provenance_blocks"] for row in rows),
            "ablated_provenance_blocks": sum(row["ablated_provenance_blocks"] for row in rows),
            "full_ask_decisions": sum(row["full_ask_decisions"] for row in rows),
            "ablated_ask_decisions": sum(row["ablated_ask_decisions"] for row in rows),
        },
        "limitation": (
            "Four developer-authored attack/control pairs, one run per mode; "
            "different model sampling trajectories. A test principal approves every ASK."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", type=Path, required=True)
    parser.add_argument("--no-provenance", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    full = json.loads(args.full.read_text("utf-8"))
    ablated = json.loads(args.no_provenance.read_text("utf-8"))
    report = compare(full, ablated)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
