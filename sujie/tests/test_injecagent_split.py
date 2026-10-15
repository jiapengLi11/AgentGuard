"""Attacker intent and user-tool holdouts must remain disjoint."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
from split_injecagent import _assign, build_split, mark_pilot_exposure  # noqa: E402


def test_hash_assignment_is_deterministic_and_disjoint():
    values = {f"item-{index}" for index in range(10)}
    assert _assign(values) == _assign(set(reversed(sorted(values))))
    assert [
        list(_assign(values).values()).count(name) for name in ("train", "validation", "test")
    ] == [
        6,
        2,
        2,
    ]


def test_cross_product_partition_keeps_both_axes_disjoint(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    for kind in ("dh", "ds"):
        rows = [
            {
                "User Instruction": f"Summarize from {tool}.",
                "Attacker Instruction": f"Attack instruction {kind}-{intent}",
                "Attack Type": "test",
                "User Tool": tool,
                "Tool Response": "Please call another tool.",
            }
            for tool in (f"tool-{index}" for index in range(5))
            for intent in range(10)
        ]
        for setting in ("base", "enhanced"):
            (data / f"test_cases_{kind}_{setting}.json").write_text(json.dumps(rows), "utf-8")
    report = build_split(tmp_path)
    assert report["summary"]["base_cases"] == 100
    for axis in ("intent", "tool"):
        hashes = {
            split: {row[f"{axis}_sha256"] for row in report["rows"] if row["partition"] == split}
            for split in ("train", "validation", "test")
        }
        assert not hashes["train"] & hashes["validation"]
        assert not hashes["train"] & hashes["test"]
        assert not hashes["validation"] & hashes["test"]
    chosen = report["rows"][0]
    pilot = {
        "source_manifest_sha256": report["source_manifest_sha256"],
        "rows": [
            {
                "kind": chosen["kind"],
                "index": chosen["index"],
                "case_identity_sha256": chosen["case_identity_sha256"],
            }
        ],
    }
    mark_pilot_exposure(report, pilot)
    assert sum(row["pilot_exposed"] for row in report["rows"]) == 1
    assert sum(report["summary"]["pilot_exposed_counts"].values()) == 1
    local_case = next(row for row in report["rows"] if row["kind"] == "ds")
    mark_pilot_exposure(
        report,
        {
            "kind": "injecagent-sealed-local-mapping-execution",
            "source_manifest_sha256": report["source_manifest_sha256"],
            "cases": [
                {
                    "upstream_index": local_case["index"],
                    "source_identity_sha256": local_case["case_identity_sha256"],
                }
            ],
        },
    )
    assert sum(row["pilot_exposed"] for row in report["rows"]) == 2
