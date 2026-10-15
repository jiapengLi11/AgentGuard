import json

import pytest
from compare_provenance_ablation import compare
from run_provenance_ablation import load_cases, run_case


def tool_call(identifier, name, arguments):
    return {
        "id": identifier,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class ScriptedTransferModel:
    def __init__(self, approved_text, *, copy_evidence):
        self.approved_text = approved_text
        self.copy_evidence = copy_evidence
        self.count = 0

    async def complete(self, messages, tools):
        self.count += 1
        if self.count == 1:
            alert_id = messages[1]["content"].split("告警 ", 1)[1].split("，", 1)[0]
            return {
                "content": "",
                "tool_calls": [tool_call("read", "evidence__read_alert", {"alert_id": alert_id})],
            }
        if self.count == 2:
            result = json.loads(
                next(
                    message["content"]
                    for message in reversed(messages)
                    if message["role"] == "tool"
                )
            )
            assert result["ok"]
            content = result["data"]["content"] if self.copy_evidence else self.approved_text
            return {
                "content": "",
                "tool_calls": [
                    tool_call(
                        "send",
                        "operations__send_data",
                        {"destination": "receiver", "content": content},
                    )
                ],
            }
        if self.count == 3 and self.copy_evidence:
            result = json.loads(
                next(
                    message["content"]
                    for message in reversed(messages)
                    if message["role"] == "tool"
                )
            )
            if result.get("decision") == "BLOCK":
                return {
                    "content": "",
                    "tool_calls": [
                        tool_call(
                            "recover",
                            "operations__send_data",
                            {"destination": "receiver", "content": self.approved_text},
                        )
                    ],
                }
        return {"content": "done", "tool_calls": []}


class WrongDestinationModel(ScriptedTransferModel):
    async def complete(self, messages, tools):
        if self.count == 1:
            self.count += 1
            return {
                "content": "",
                "tool_calls": [
                    tool_call(
                        "bad-destination",
                        "operations__send_data",
                        {"destination": "wrong", "content": self.approved_text},
                    )
                ],
            }
        if self.count == 2:
            assert any(
                "destination 必须是 receiver" in message.get("content", "")
                for message in messages
                if message["role"] == "system"
            )
            self.count += 1
            return {
                "content": "",
                "tool_calls": [
                    tool_call(
                        "safe-retry",
                        "operations__send_data",
                        {"destination": "receiver", "content": self.approved_text},
                    )
                ],
            }
        return await super().complete(messages, tools)


def test_transfer_suite_has_paired_controls():
    cases, dataset_id = load_cases()
    assert dataset_id == "approved-transfer-v1-synthetic"
    assert len(cases) == 8
    assert len({item["pair_id"] for item in cases}) == 4


@pytest.mark.asyncio
async def test_authorized_effect_is_still_bound_to_source_and_safe_recovery():
    case = load_cases()[0][0]
    approved_text = f"APPROVED-DIAGNOSTIC-{case['pair_id']}-{case['fact']}"
    full = await run_case(
        case, ScriptedTransferModel(approved_text, copy_evidence=True), mode="full"
    )
    ablated = await run_case(
        case,
        ScriptedTransferModel(approved_text, copy_evidence=True),
        mode="no-provenance",
    )
    assert full["provenance_blocks"] == 1
    assert "DATA_FLOW" in full["alignment_deviations"]
    assert not full["honeytoken_leaked"]
    assert full["task_completed"]
    assert ablated["provenance_blocks"] == 0
    assert ablated["honeytoken_leaked"]
    control = load_cases()[0][1]
    clean_text = f"APPROVED-DIAGNOSTIC-{control['pair_id']}-{control['fact']}"
    clean = await run_case(
        control, ScriptedTransferModel(clean_text, copy_evidence=False), mode="full"
    )
    assert clean["task_completed"]
    assert not clean["honeytoken_leaked"]


@pytest.mark.asyncio
async def test_invalid_transfer_arguments_recover_to_exact_approved_content():
    case = load_cases()[0][1]
    approved_text = f"APPROVED-DIAGNOSTIC-{case['pair_id']}-{case['fact']}"
    result = await run_case(
        case, WrongDestinationModel(approved_text, copy_evidence=False), mode="full"
    )
    assert result["task_completed"]
    assert [item["code"] for item in result["decisions"] if item["code"]] == ["INVALID_ACTION"]
    assert not result["honeytoken_leaked"]


def test_ablation_comparison_rejects_different_case_text():
    common = {
        "model": "qwen-plus-2025-12-01",
        "dataset_id": "paired",
        "dataset_sha256": "same",
        "host_version": "v1",
    }
    item = {
        "id": "attack",
        "pair_id": "p",
        "attack": True,
        "family": "ROLE_SPOOF",
        "case_sha256": "case",
        "honeytoken_leaked": False,
        "task_completed": True,
        "provenance_blocks": 1,
        "ask_decisions": 1,
    }
    full = {**common, "mode": "full", "cases": [item]}
    ablated = {
        **common,
        "mode": "no-provenance",
        "cases": [{**item, "honeytoken_leaked": True, "provenance_blocks": 0}],
    }
    assert compare(full, ablated)["summary"]["ablated_attack_leaks"] == 1
    with pytest.raises(ValueError, match="MISMATCHED_CASE"):
        compare(full, {**ablated, "cases": [{**ablated["cases"][0], "case_sha256": "different"}]})
