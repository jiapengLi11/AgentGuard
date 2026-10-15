"""Input selection, analytical use and operational delegation are different gates."""

import pytest
from sujie_control.profiles import records
from sujie_demo_agent.delegated_agent import AnalysisDelegation
from sujie_demo_agent.model_budget import ModelBudget
from sujie_demo_agent.protected_model import ProtectedModel
from sujie_gateway.contracts import TaskGrant
from sujie_gateway.m1_runtime import M1Gateway, new_id


class Proxy:
    registry = {}


def prepare():
    contract, grant = records("delegated-report")
    gateway = M1Gateway(Proxy(), contract, grant)
    ordinary = gateway.register_host_content("Public synthetic analysis facts")
    event = gateway.trace.emit("CONTENT_REGISTERED", actor_id=grant.to_dict()["subject_id"])
    secret = gateway.trace.create_artifact(
        "SYNTHETIC-PRIVATE-MATERIAL",
        source_event_id=event,
        source_id="trusted-fault",
        confidentiality="SECRET",
    )
    gateway._exposed_artifacts.add(secret)  # Deliberate Host fault, never a model option.
    child = TaskGrant(
        grant.to_dict()
        | {
            "grant_id": new_id(),
            "subject_id": new_id(),
            "parent_grant_id": grant.to_dict()["grant_id"],
            "effects": ["file.read"],
            "resource_scopes": ["/workspace/case-001/context/assets.json"],
            "budgets": {"tool_calls": 2, "network_calls": 0, "subagents": 0},
        }
    )
    return gateway, ordinary, secret, child


@pytest.mark.asyncio
async def test_selected_ordinary_source_does_not_inherit_unrelated_secret_context():
    parent, ordinary, secret, grant = prepare()
    decision, child = await parent.spawn_child(grant, analysis_inputs=(ordinary,))
    assert decision["ok"] and child is not None
    assert child._exposed_artifacts == {ordinary}
    seen = []

    class Model:
        async def complete(self, messages, tools):
            seen.append(messages)
            return {"content": "analysis", "tool_calls": []}

    guarded = ProtectedModel(Model(), child, purpose="SUBAGENT")
    await guarded.complete(
        [{"role": "user", "content": child.trace.artifact_contents[ordinary]}], []
    )
    assert len(seen) == 1 and secret not in guarded.response_artifacts
    assert "SYNTHETIC-PRIVATE-MATERIAL" not in str(seen)
    assert "DELEGATE" in child.trace.artifacts[ordinary].to_dict()["forbidden_uses"]
    assert "TRANSFER" not in child.grant.to_dict()["effects"]


@pytest.mark.asyncio
async def test_secret_or_forged_input_never_creates_child_model():
    gateway, ordinary, secret, _ = prepare()
    factories = []

    def factory():
        factories.append(True)
        raise AssertionError("MUST_NOT_CREATE_MODEL")

    handler = AnalysisDelegation(gateway, factory, ModelBudget())
    for arguments, code in (
        ({"role": "review", "artifact_ids": [secret]}, "DELEGATION_SENSITIVE_INPUT"),
        ({"role": "review", "artifact_ids": [new_id()]}, "INVALID_DELEGATION"),
        ({"role": "verify", "artifact_ids": [ordinary]}, "INVALID_DELEGATION"),
        (
            {"role": "review", "artifact_ids": [ordinary], "text": "SYNTHETIC-PRIVATE-MATERIAL"},
            "INVALID_DELEGATION",
        ),
        ({"role": "review", "artifact_ids": [ordinary], "effects": ["exec"]}, "INVALID_DELEGATION"),
    ):
        result = await handler.invoke(arguments)
        assert result["code"] == code
    assert factories == [] and handler.records == []


@pytest.mark.asyncio
async def test_analytical_input_cannot_expand_effects_or_enable_generic_delegation():
    gateway, ordinary, _, grant = prepare()
    bad = TaskGrant(grant.to_dict() | {"effects": ["file.read", "file.write:report"]})
    result, child = await gateway.spawn_child(bad, analysis_inputs=(ordinary,))
    assert child is None and result["code"] == "ANALYSIS_CHILD_EFFECT_FORBIDDEN"
    result, child = await gateway.spawn_child(grant)
    assert child is None and result["code"] == "PROVENANCE_FORBIDS_DELEGATE"
    result, child = await gateway.spawn_child(grant, analysis_inputs=(new_id(),))
    assert child is None and result["code"] == "ANALYSIS_INPUT_INVALID"
