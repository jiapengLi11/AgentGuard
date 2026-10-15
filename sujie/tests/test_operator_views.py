"""Public operator projections expose metadata and only matched sanitized previews."""

import pytest
from sujie_control.views import approval_view, event_view, impact_view
from sujie_gateway.m1_runtime import sha
from verify_operator_export import verify


def test_operator_event_projection_excludes_raw_tool_arguments_and_finding_snippet():
    event = {"event_id": "e", "artifact_ids": [], "event_type": "DETECTION_FINDING"}
    payload = {
        "content": "PRIVATE_BODY",
        "arguments": {"password": "PRIVATE_ARGUMENT"},
        "finding": {
            "attack_source": "TOOL_RESULT",
            "attack_family": "INSTRUCTION_OVERRIDE",
            "confidence": 0.9,
            "reasons": ["instruction_override"],
            "detector_version": "test",
            "snippet": "PRIVATE_SNIPPET",
        },
    }
    result = event_view(event, payload)
    assert "PRIVATE" not in str(result)
    assert result["details"]["finding"]["confidence"] == 0.9


def test_review_hash_is_stable_across_status_and_preview_is_input_bound():
    summary = {
        "decision_id": "decision",
        "action_id": "action",
        "effect": {"kind": "data.transfer", "resources": ["https://receiver.invalid/upload"]},
        "arguments_hash": sha("args"),
        "input_content_hash": sha("PUBLIC_IPV4_IOCS\n8.8.8.8"),
        "provenance_snapshot_hash": sha("provenance"),
        "policy_snapshot_hash": sha("policy"),
        "expires_at": "2030-01-01T00:00:00Z",
        "status": "PENDING",
    }
    initial = approval_view(summary, "PUBLIC_IPV4_IOCS\n8.8.8.8")
    assert initial["safe_preview"] == "PUBLIC_IPV4_IOCS\n8.8.8.8"
    approved = approval_view({**summary, "status": "APPROVED"}, "different input")
    assert approved["review_hash"] == initial["review_hash"]
    assert "safe_preview" not in approved
    changed = approval_view({**summary, "arguments_hash": sha("other args")}, None)
    assert changed["review_hash"] != initial["review_hash"]


def test_impact_traverses_descendants_and_only_records_actual_resource_effects():
    artifacts = [
        {"artifact_id": "a", "parents": []},
        {"artifact_id": "b", "parents": ["a"]},
        {"artifact_id": "c", "parents": ["b"]},
        {"artifact_id": "unrelated", "parents": []},
    ]
    events = [
        {
            "event_id": "e1",
            "artifact_ids": ["c"],
            "event_type": "RESOURCE_AFFECTED",
            "details": {"resources": ["written"]},
        },
        {
            "event_id": "e2",
            "artifact_ids": ["a"],
            "event_type": "TOOL_CALL_DECIDED",
            "details": {"resources": ["blocked"]},
        },
        {
            "event_id": "e3",
            "artifact_ids": ["unrelated"],
            "event_type": "RESOURCE_AFFECTED",
            "details": {"resources": ["other"]},
        },
    ]
    assert impact_view(artifacts, events, "a") == {
        "artifact_ids": ["a", "b", "c"],
        "event_ids": ["e1", "e2"],
        "resources": ["written"],
    }


def test_export_verifier_rejects_tampered_digest_and_invalid_links():
    payload = {
        "schema_version": "sujie-operator-export-v1",
        "mode": "sealed-local-demo-fixed-actions",
        "task": {"artifacts": [{"artifact_id": "a", "parents": ["missing"]}], "events": []},
    }
    with pytest.raises(ValueError, match="EXPORT_HASH_MISMATCH"):
        verify({"payload": payload, "export_hash": sha("different")})
    with pytest.raises(ValueError, match="INVALID_ARTIFACT_GRAPH"):
        verify({"payload": payload, "export_hash": sha(payload)})
