from sujie_gateway.contracts import SemanticAction, TaskContract, TaskGrant
from sujie_gateway.m1_runtime import M1Policy


def test_M1_DECISION_001_three_state_ask(fixture_document):
    action = fixture_document("semantic-action")
    action["effect"].update(
        kind="data.transfer",
        operation="HTTP_POST",
        resources=["https://receiver.invalid/upload"],
        destination_trust="UNTRUSTED_EXTERNAL",
        reversible=False,
    )
    contract = fixture_document("task-contract")
    contract["expires_at"] = "2099-01-01T00:00:00Z"
    contract["policy_snapshot_hash"] = M1Policy().snapshot_hash
    contract["forbidden_effects"] = ["credential.read", "git.push"]
    contract["allowed_purposes"].append("TRANSFER")
    contract["allowed_effects"].append(
        {"kind": "data.transfer", "resource": "https://receiver.invalid/upload"}
    )
    grant = fixture_document("task-grant")
    grant["expires_at"] = "2099-01-01T00:00:00Z"
    grant["effects"].append("data.transfer")
    decision = M1Policy().decide(SemanticAction(action), TaskContract(contract), TaskGrant(grant))
    assert (decision.decision, decision.hard_block) == ("ASK", False)


def test_M1_DECISION_006_transfer_effect_does_not_imply_transfer_purpose(fixture_document):
    action = fixture_document("semantic-action")
    action["effect"].update(
        kind="data.transfer",
        operation="HTTP_POST",
        resources=["https://receiver.invalid/upload"],
        destination_trust="UNTRUSTED_EXTERNAL",
        reversible=False,
    )
    contract = fixture_document("task-contract")
    contract["expires_at"] = "2099-01-01T00:00:00Z"
    contract["policy_snapshot_hash"] = M1Policy().snapshot_hash
    contract["forbidden_effects"] = ["credential.read", "git.push"]
    contract["allowed_effects"].append(
        {"kind": "data.transfer", "resource": "https://receiver.invalid/upload"}
    )
    grant = fixture_document("task-grant")
    grant["expires_at"] = "2099-01-01T00:00:00Z"
    grant["effects"].append("data.transfer")
    decision = M1Policy().decide(SemanticAction(action), TaskContract(contract), TaskGrant(grant))
    assert (decision.decision, decision.hard_block, decision.reason) == (
        "BLOCK",
        True,
        "PURPOSE_NOT_ALLOWED",
    )


def test_M1_DECISION_002_forbidden_is_block(fixture_document):
    action = fixture_document("semantic-action")
    action["effect"]["kind"] = "credential.read"
    contract = fixture_document("task-contract")
    contract["expires_at"] = "2099-01-01T00:00:00Z"
    contract["policy_snapshot_hash"] = M1Policy().snapshot_hash
    grant = fixture_document("task-grant")
    grant["expires_at"] = "2099-01-01T00:00:00Z"
    grant["effects"].append("credential.read")
    decision = M1Policy().decide(SemanticAction(action), TaskContract(contract), TaskGrant(grant))
    assert (decision.decision, decision.hard_block) == ("BLOCK", True)


def test_M1_DECISION_003_expired_contract_is_hard_block(fixture_document):
    action = fixture_document("semantic-action")
    contract = fixture_document("task-contract")
    contract["policy_snapshot_hash"] = M1Policy().snapshot_hash
    grant = fixture_document("task-grant")
    grant["expires_at"] = "2099-01-01T00:00:00Z"
    decision = M1Policy().decide(SemanticAction(action), TaskContract(contract), TaskGrant(grant))
    assert (decision.decision, decision.hard_block, decision.reason) == (
        "BLOCK",
        True,
        "GRANT_EXPIRED",
    )


def test_M1_DECISION_004_policy_drift_is_hard_block(fixture_document):
    action = fixture_document("semantic-action")
    contract = fixture_document("task-contract")
    contract["expires_at"] = "2099-01-01T00:00:00Z"
    grant = fixture_document("task-grant")
    grant["expires_at"] = "2099-01-01T00:00:00Z"
    decision = M1Policy().decide(SemanticAction(action), TaskContract(contract), TaskGrant(grant))
    assert (decision.decision, decision.hard_block, decision.reason) == (
        "BLOCK",
        True,
        "POLICY_SNAPSHOT_MISMATCH",
    )


def test_M1_DECISION_005_legacy_external_alias_still_forbids_transfer(fixture_document):
    action = fixture_document("semantic-action")
    action["effect"].update(
        kind="data.transfer",
        operation="HTTP_POST",
        resources=["https://receiver.invalid/upload"],
        destination_trust="UNTRUSTED_EXTERNAL",
        reversible=False,
    )
    contract = fixture_document("task-contract")
    contract["expires_at"] = "2099-01-01T00:00:00Z"
    contract["policy_snapshot_hash"] = M1Policy().snapshot_hash
    contract["allowed_effects"].append(
        {"kind": "data.transfer", "resource": "https://receiver.invalid/upload"}
    )
    grant = fixture_document("task-grant")
    grant["expires_at"] = "2099-01-01T00:00:00Z"
    grant["effects"].append("data.transfer")
    decision = M1Policy().decide(SemanticAction(action), TaskContract(contract), TaskGrant(grant))
    assert (decision.decision, decision.hard_block, decision.reason) == (
        "BLOCK",
        True,
        "CONTRACT_FORBIDS_EFFECT",
    )
