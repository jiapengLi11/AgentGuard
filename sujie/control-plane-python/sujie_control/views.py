"""Metadata projections: operator trace views never serialize artifact bodies."""

from sujie_gateway.m1_runtime import sha


def event_view(event: dict, payload: dict) -> dict:
    details = {
        key: payload[key]
        for key in (
            "tool",
            "decision",
            "reason",
            "ok",
            "code",
            "kind",
            "resources",
            "transformation",
            "status",
            "binding_valid",
            "arguments_hash",
            "git_state",
            "role",
            "depth",
            "child_subject_id",
            "parent_subject_id",
            "grant_hash",
            "input_hashes",
            "grant_revoked",
            "stop_reason",
            "model_requests",
            "phase_name",
            "session_id",
            "contract_id",
            "key",
            "revision",
            "content_sha256",
            "variant",
            "variant_policy_hash",
            "shared_floor_hash",
        )
        if key in payload
    }
    if payload.get("alignment"):
        details["alignment"] = payload["alignment"]
    if "semantic_action" in payload:
        details["semantic_action"] = payload["semantic_action"]
    if "visible_plan" in payload:
        details["visible_plan"] = payload["visible_plan"]
        details["plan_text_hash"] = payload["plan_text_hash"]
    if "record" in payload:
        details["record"] = {"risk": payload["record"]["risk"]}
    if "finding" in payload:
        finding = payload["finding"]
        details["finding"] = {
            key: finding[key]
            for key in (
                "attack_source",
                "attack_family",
                "confidence",
                "reasons",
                "detector_version",
            )
        }
        details["finding"]["confidence_interpretation"] = "uncalibrated-signal-not-probability"
    return {**event, "details": details}


def artifact_view(envelope: dict) -> dict:
    return {
        key: envelope[key]
        for key in (
            "artifact_id",
            "content_hash",
            "origin",
            "authority",
            "integrity",
            "confidentiality",
            "allowed_uses",
            "forbidden_uses",
            "parents",
            "transformations",
            "created_at",
        )
    }


def approval_view(summary: dict, ioc_content: str | None) -> dict:
    stable = {
        key: summary[key]
        for key in (
            "decision_id",
            "action_id",
            "effect",
            "arguments_hash",
            "input_content_hash",
            "provenance_snapshot_hash",
            "policy_snapshot_hash",
            "expires_at",
        )
    }
    if "git_review" in summary:
        stable["git_review"] = summary["git_review"]
    result = {**summary, "review_hash": sha(stable)}
    if ioc_content is not None and sha(ioc_content) == summary["input_content_hash"]:
        result["safe_preview"] = ioc_content
    return result


def impact_view(artifacts: list[dict], events: list[dict], artifact_id: str) -> dict:
    if artifact_id not in {item["artifact_id"] for item in artifacts}:
        raise ValueError("ARTIFACT_NOT_FOUND")
    descendants = {artifact_id}
    while True:
        added = {item["artifact_id"] for item in artifacts if set(item["parents"]) & descendants}
        if added <= descendants:
            break
        descendants |= added
    affected = [event for event in events if set(event["artifact_ids"]) & descendants]
    return {
        "artifact_ids": sorted(descendants),
        "event_ids": [event["event_id"] for event in affected],
        "resources": sorted(
            {
                resource
                for event in affected
                if event["event_type"] == "RESOURCE_AFFECTED"
                for resource in event["details"].get("resources", [])
            }
        ),
    }
