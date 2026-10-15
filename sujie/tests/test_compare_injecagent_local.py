"""Paired execution claims require matching source, prompt and exact cases."""

from copy import deepcopy

import pytest
from compare_injecagent_local import compare


def fixture_report(mode: str) -> dict:
    report = {
        "kind": "injecagent-sealed-local-mapping-execution",
        "model": "fixture",
        "host_version": "fixture",
        "prompt_sha256": "prompt",
        "source_manifest_sha256": "source",
        "tool_catalog_sha256": "tools",
        "dataset_sha256": "data",
        "base_user_tasks": 1,
        "attack_intents": 1,
        "repeats": 1,
        "modes": [mode],
        "cases": [],
    }
    for attack in (True, False):
        report["cases"].append(
            {
                "id": "attack" if attack else "clean",
                "pair_id": "pair",
                "attack": attack,
                "mode": mode,
                "repeat": 1,
                "user_tool": "read",
                "private_tool": "private",
                "upstream_index": 1,
                "source_identity_sha256": "identity",
                "response_sha256": str(attack),
                "private_read_attempted": False,
                "private_read_succeeded": False,
                "email_attempted": False,
                "receiver_requests": 0,
                "honeytoken_leaked": False,
                "final_honeytoken_exposed": False,
                "task_completed": True,
                "total_tokens": 0,
                "decisions": [],
            }
        )
    return report


def test_compare_rejects_incompatible_and_incomplete_runs():
    baseline, full = fixture_report("unsafe"), fixture_report("full")
    assert compare([baseline, full])["summary"]["full"]["clean_tasks_completed"] == 1
    altered = deepcopy(full)
    altered["prompt_sha256"] = "different"
    with pytest.raises(ValueError, match="CONFIGURATION_MISMATCH"):
        compare([baseline, altered])
    altered = deepcopy(full)
    altered["cases"].pop()
    with pytest.raises(ValueError, match="INCOMPLETE_LOCAL_PAIRED_RUN"):
        compare([baseline, altered])


def test_compare_rejects_different_case_payload_and_duplicate_modes():
    baseline, full = fixture_report("unsafe"), fixture_report("full")
    full["cases"][0]["response_sha256"] = "changed-payload"
    with pytest.raises(ValueError, match="CASE_BINDING_MISMATCH"):
        compare([baseline, full])
    with pytest.raises(ValueError, match="DUPLICATE_LOCAL_MODE"):
        compare([baseline, baseline])
