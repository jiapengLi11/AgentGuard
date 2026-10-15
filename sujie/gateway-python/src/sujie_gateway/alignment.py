"""Explain a blocked semantic action from trusted contract and action fields.

This is a post-decision explanation. It never changes authorization and never
interprets the untrusted tool text as a source of authority.
"""

from __future__ import annotations

from typing import Any


def explain_alignment(
    reason: str,
    action: dict[str, Any],
    contract: dict[str, Any],
    grant: dict[str, Any],
    *,
    required_purpose: str | None = None,
    copied_artifact_id: str | None = None,
) -> dict[str, Any] | None:
    """Return one of GOAL, RESOURCE, SIDE_EFFECT, DATA_FLOW, or no deviation.

    Administrative failures such as expiry or policy drift are not semantic
    deviations and return None. Facts use only normalized metadata, never args.
    """
    effect = action["effect"]
    kind = effect["kind"]
    resources = effect["resources"]
    permitted_scopes = [
        item["resource"] for item in contract["allowed_effects"] if item["kind"] == kind
    ]

    def fact(field: str, values: list[str] | str) -> dict[str, str]:
        summary = ", ".join(values) if isinstance(values, list) else values
        return {"field": field, "summary": summary[:512] or "(none)"}

    if reason == "PURPOSE_NOT_ALLOWED":
        category = "GOAL"
        facts = [
            fact("action.effect.kind", kind),
            fact("runtime.required_purpose", required_purpose or "UNDEFINED"),
            fact("contract.allowed_purposes", contract["allowed_purposes"]),
        ]
    elif reason == "RESOURCE_OUT_OF_SCOPE" or (
        reason == "EFFECT_OUTSIDE_CONTRACT" and permitted_scopes
    ):
        category = "RESOURCE"
        facts = [
            fact("action.effect.resources", resources),
            fact(
                "grant.resource_scopes"
                if reason == "RESOURCE_OUT_OF_SCOPE"
                else "contract.allowed_effects.resource",
                grant["resource_scopes"] if reason == "RESOURCE_OUT_OF_SCOPE" else permitted_scopes,
            ),
        ]
    elif reason == "hard_block_unregistered_git_target":
        category = "RESOURCE"
        facts = [
            fact("action.effect.operation", effect["operation"]),
            fact("runtime.git_constraint", "PINNED_REMOTE_REF_COMMIT_OLD_VALUE_AND_STATE"),
            fact("action.effect.resources", resources),
        ]
    elif reason == "hard_block_unapproved_process":
        category = "SIDE_EFFECT"
        facts = [
            fact("action.effect.kind", kind),
            fact("action.effect.operation", effect["operation"]),
            fact("runtime.command_constraint", "ONLY_REGISTERED_INSPECTION_PROGRAM_AND_ARGV"),
            fact("action.effect.resources", resources),
        ]
    elif reason in {"EFFECT_NOT_GRANTED", "CONTRACT_FORBIDS_EFFECT", "EFFECT_OUTSIDE_CONTRACT"}:
        category = "SIDE_EFFECT"
        facts = [
            fact("action.effect.kind", kind),
            fact(
                "grant.effects"
                if reason == "EFFECT_NOT_GRANTED"
                else "contract.forbidden_effects"
                if reason == "CONTRACT_FORBIDS_EFFECT"
                else "contract.allowed_effects.kind",
                grant["effects"]
                if reason == "EFFECT_NOT_GRANTED"
                else contract["forbidden_effects"]
                if reason == "CONTRACT_FORBIDS_EFFECT"
                else [item["kind"] for item in contract["allowed_effects"]],
            ),
        ]
    elif reason in {"PROVENANCE_FORBIDS_TRANSFER", "EGRESS_SOURCE_UNREGISTERED"}:
        category = "DATA_FLOW"
        facts = [
            fact("action.effect.destination_trust", effect["destination_trust"]),
            fact("action.input_artifacts", action["input_artifacts"]),
        ]
        if copied_artifact_id is not None:
            facts.append(fact("provenance.copied_artifact_id", copied_artifact_id))
    else:
        return None
    return {"deviation": category, "reason_code": reason, "facts": facts}
