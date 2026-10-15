"""Task-level explanation from trusted action metadata and recorded effects.

No authorization decisions and no interpretation of model text as authority.
Context association is explicitly weaker than a causal claim.
"""

from __future__ import annotations


def assess_sequence(contract: dict, events: list[dict], payloads: dict, artifacts: dict) -> dict:
    steps, proposals, actions, findings, plans = [], {}, {}, [], []

    def ancestors(identifiers):
        seen, pending = set(), list(identifiers)
        while pending:
            identifier = pending.pop()
            if identifier in seen or identifier not in artifacts:
                continue
            seen.add(identifier)
            pending.extend(artifacts[identifier].get("parents", []))
        return sorted(seen)

    for event in events:
        data = payloads.get(event["event_id"], {})
        kind = event["event_type"]
        if kind == "DETECTION_FINDING":
            finding = data.get("finding", {})
            findings.append(
                {
                    "event_id": event["event_id"],
                    "artifact_ids": event.get("artifact_ids", []),
                    "attack_source": finding.get("attack_source"),
                    "attack_family": finding.get("attack_family"),
                    "interpretation": "UNCALIBRATED_DETECTION_SIGNAL",
                }
            )
        elif kind == "CONTENT_REGISTERED" and data.get("kind") == "MODEL_VISIBLE_PLAN":
            plans.append(
                {
                    "event_id": event["event_id"],
                    "calls": data["visible_plan"],
                    "plan_text_hash": data["plan_text_hash"],
                    "scope": "MODEL_VISIBLE_TOOL_PROPOSALS_NOT_HIDDEN_REASONING",
                }
            )
        elif kind == "TOOL_PROPOSED":
            step = {
                "ordinal": len(steps) + 1,
                "proposal_event_id": event["event_id"],
                "actor_id": event.get("actor_id"),
                "timestamp": event.get("timestamp"),
                "tool": data.get("tool", "unknown"),
                "arguments_hash": data.get("arguments_hash"),
                "input_artifacts": list(event.get("artifact_ids", [])),
                "model_plan_event_ids": [
                    parent
                    for parent in event.get("parent_event_ids", [])
                    if payloads.get(parent, {}).get("kind") == "MODEL_VISIBLE_PLAN"
                ],
                "decision": None,
                "reason": None,
                "effect": None,
                "deviation": None,
                "execution": "NOT_EXECUTED",
                "execution_event_ids": [],
                "observed_resources": [],
            }
            steps.append(step)
            proposals[event["event_id"]] = step
        elif kind == "TOOL_CALL_DECIDED":
            step = next(
                (proposals[p] for p in event.get("parent_event_ids", []) if p in proposals), None
            )
            if step is None:
                continue
            semantic = data.get("semantic_action", {})
            step.update(
                {
                    "decision_event_id": event["event_id"],
                    "decision": data.get("decision"),
                    "reason": data.get("reason"),
                    "effect": semantic.get("effect"),
                    "deviation": data.get("alignment"),
                    "risk": data.get("record", {}).get("risk"),
                }
            )
            if event.get("action_id"):
                actions[event["action_id"]] = step
        elif kind in {"EXECUTION_RESULT", "RESOURCE_READ", "RESOURCE_AFFECTED"}:
            step = actions.get(event.get("action_id"))
            if step is None:
                continue
            if kind == "EXECUTION_RESULT":
                step["execution"] = "CONFIRMED" if data.get("ok") else "UNKNOWN"
                step["execution_event_ids"].append(event["event_id"])
            elif kind == "RESOURCE_AFFECTED":
                step["observed_resources"].extend(data.get("resources", []))
            else:
                step["read_artifacts"] = list(event.get("artifact_ids", []))
                step["observed_resources"].extend((step["effect"] or {}).get("resources", []))

    deviations = []
    for step in steps:
        lineage = ancestors(step["input_artifacts"])
        step["source_ancestors"] = lineage
        step["associated_findings"] = [
            finding["event_id"]
            for finding in findings
            if set(finding["artifact_ids"]) & set(lineage)
        ]
        step["observed_resources"] = sorted(set(step["observed_resources"]))
        if step["deviation"]:
            deviations.append({"ordinal": step["ordinal"], **step["deviation"]})

    chains = []
    for index, first in enumerate(steps):
        if (first["effect"] or {}).get("kind") != "credential.read":
            continue
        for second in steps[index + 1 :]:
            if (second["effect"] or {}).get("kind") not in {
                "data.transfer",
                "external.data_transfer",
            }:
                continue
            shared = sorted(set(first["source_ancestors"]) & set(second["source_ancestors"]))
            # Temporal adjacency is not evidence of the bytes actually transmitted.
            chains.append(
                {
                    "kind": "CREDENTIAL_READ_THEN_TRANSFER_PROPOSALS",
                    "ordinals": [first["ordinal"], second["ordinal"]],
                    "shared_context_artifacts": shared,
                    "read_execution": first["execution"],
                    "transfer_execution": second["execution"],
                    "data_flow_proven": False,
                    "interpretation": "SEQUENCE_ASSOCIATION_NOT_CAUSAL_PROOF",
                }
            )

    unknown = [step["ordinal"] for step in steps if step["execution"] == "UNKNOWN"]
    blocked = [step["ordinal"] for step in steps if step["decision"] == "BLOCK"]
    confirmed = [step["ordinal"] for step in steps if step["execution"] == "CONFIRMED"]
    if unknown:
        conclusion = "EXECUTION_RESULT_REQUIRES_VERIFICATION"
    elif deviations:
        conclusion = "TASK_DEVIATION_OBSERVED"
    elif findings:
        conclusion = "SUSPICIOUS_CONTEXT_WITHOUT_PROVEN_TOOL_DEVIATION"
    elif blocked:
        conclusion = "ACTION_REJECTED_WITHOUT_SEMANTIC_EVIDENCE"
    else:
        conclusion = "NO_RECORDED_TASK_DEVIATION"
    return {
        "schema_version": "sujie-sequence-assessment-v1",
        "contract_id": contract["contract_id"],
        "trusted_goal": contract["trusted_goal"],
        "allowed_purposes": contract["allowed_purposes"],
        "scope": "TRUSTED_CONTRACT_AND_RECORDED_ACTIONS_NOT_MODEL_SELF_ASSESSMENT",
        "conclusion": conclusion,
        "tool_sequence": steps,
        "visible_plans": plans,
        "deviations": deviations,
        "suspicious_chains": chains,
        "findings": findings,
        "blocked_ordinals": blocked,
        "confirmed_execution_ordinals": confirmed,
        "unknown_execution_ordinals": unknown,
        "injection_attribution": "CONTEXT_ASSOCIATION_NOT_CAUSAL_PROOF",
    }
