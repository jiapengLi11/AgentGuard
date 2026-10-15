from sujie_gateway.alignment import explain_alignment


def test_alignment_grounds_four_deviations_in_trusted_metadata(fixture_document):
    action = fixture_document("semantic-action")
    contract = fixture_document("task-contract")
    grant = fixture_document("task-grant")
    action["effect"]["kind"] = "data.transfer"
    action["effect"]["resources"] = ["https://receiver.invalid/upload"]
    action["effect"]["destination_trust"] = "UNTRUSTED_EXTERNAL"
    action["input_artifacts"] = [action["action_id"]]

    goal = explain_alignment(
        "PURPOSE_NOT_ALLOWED", action, contract, grant, required_purpose="TRANSFER"
    )
    assert goal["deviation"] == "GOAL"
    assert {item["field"] for item in goal["facts"]} == {
        "action.effect.kind",
        "runtime.required_purpose",
        "contract.allowed_purposes",
    }

    resource = explain_alignment("RESOURCE_OUT_OF_SCOPE", action, contract, grant)
    assert resource["deviation"] == "RESOURCE"
    assert resource["facts"][1]["summary"] == ", ".join(grant["resource_scopes"])

    side_effect = explain_alignment("CONTRACT_FORBIDS_EFFECT", action, contract, grant)
    assert side_effect["deviation"] == "SIDE_EFFECT"
    assert side_effect["facts"][1]["summary"] == ", ".join(contract["forbidden_effects"])

    flow = explain_alignment(
        "PROVENANCE_FORBIDS_TRANSFER",
        action,
        contract,
        grant,
        copied_artifact_id=action["action_id"],
    )
    assert flow["deviation"] == "DATA_FLOW"
    assert flow["facts"][-1]["summary"] == action["action_id"]
    assert explain_alignment("GRANT_EXPIRED", action, contract, grant) is None
    assert "secret body" not in str([goal, resource, side_effect, flow])
