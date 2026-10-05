from sujie_gateway.contracts import SemanticAction, TaskContract, TaskGrant
from sujie_gateway.m1_runtime import M1Policy


def test_M1_DECISION_001_three_state_ask(fixture_document, now):
    action = fixture_document("semantic-action")
    action["effect"].update(
        kind="data.transfer",
        operation="HTTP_POST",
        resources=["https://receiver.invalid/upload"],
        destination_trust="UNTRUSTED_EXTERNAL",
        reversible=False,
    )
    contract = fixture_document("task-contract")
    contract["forbidden_effects"].remove("external.data_transfer")
    contract["allowed_effects"].append(
        {"kind": "data.transfer", "resource": "https://receiver.invalid/upload"}
    )
    grant = fixture_document("task-grant")
    grant["effects"].append("data.transfer")
    grant["resource_scopes"].append("https://receiver.invalid/upload")
    grant["budgets"]["network_calls"] = 1
    decision = M1Policy().decide(
        SemanticAction(action), TaskContract(contract), TaskGrant(grant), now=now
    )
    assert (decision.decision, decision.hard_block) == ("ASK", False)


def test_M1_DECISION_002_forbidden_is_block(fixture_document, now):
    action = fixture_document("semantic-action")
    action["effect"]["kind"] = "credential.read"
    contract = fixture_document("task-contract")
    grant = fixture_document("task-grant")
    grant["effects"].append("credential.read")
    decision = M1Policy().decide(
        SemanticAction(action), TaskContract(contract), TaskGrant(grant), now=now
    )
    assert (decision.decision, decision.hard_block) == ("BLOCK", True)
