"""Actual bounded analysis agents with explicit inputs and shrinking capabilities."""

from __future__ import annotations

import asyncio
import json
import re

from sujie_gateway.contracts import TaskGrant
from sujie_gateway.m1_runtime import M1Gateway, new_id, sha, utc_now, utc_text
from sujie_gateway.model_context import ContextError, contains_protected

from .bailian_agent import ModelProtocolError, run_tool_agent
from .protected_model import ProtectedModel

ASSET_RESOURCE = "case-001/context/assets.json"
BASELINE_RESOURCE = "/workspace/case-001/baseline.txt"


class AnalysisDelegation:
    """A single-use role adapter. Models select data IDs, never grants or instructions.

    Role REVIEW may read the inventory and delegate VERIFY. VERIFY may only read
    the baseline. Both run in the trusted Host, not an OS isolation boundary.
    """

    def __init__(
        self,
        gateway: M1Gateway,
        model_factory,
        budget,
        *,
        protected_values=(),
        tokenizer=None,
        depth=0,
        records=None,
        timeout=90.0,
    ):
        if depth not in {0, 1} or not 0 < timeout <= 300:
            raise ValueError("INVALID_ANALYSIS_HOST")
        self.gateway, self.model_factory, self.budget = gateway, model_factory, budget
        self.protected_values, self.tokenizer = tuple(protected_values), tokenizer
        self.depth, self.timeout = depth, timeout
        self.records = [] if records is None else records
        self.used = False

    def definition(self):
        return {
            "type": "function",
            "function": {
                "name": "host__delegate",
                "description": "Start the registered read-only analysis role with selected source artifact IDs. The Host supplies its fixed goal, narrower grants, independent conversation and shared budget. Raw text or custom permissions are not accepted.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "role": {
                            "type": "string",
                            "enum": ["review" if self.depth == 0 else "verify"],
                        },
                        "artifact_ids": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 8,
                            "uniqueItems": True,
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["role", "artifact_ids"],
                },
            },
        }

    async def invoke(self, arguments: dict) -> dict:
        role = "review" if self.depth == 0 else "verify"
        identifiers = arguments.get("artifact_ids")
        if (
            set(arguments) != {"role", "artifact_ids"}
            or arguments.get("role") != role
            or not isinstance(identifiers, list)
            or not 1 <= len(identifiers) <= 8
            or any(not isinstance(item, str) for item in identifiers)
            or len(set(identifiers)) != len(identifiers)
            or not set(identifiers) <= self.gateway._exposed_artifacts
        ):
            return await self.gateway.record_host_block(
                "host.delegate", arguments, "INVALID_DELEGATION"
            )
        if self.used:
            return await self.gateway.record_host_block(
                "host.delegate", arguments, "DELEGATION_ALREADY_USED"
            )
        try:
            texts = [self.gateway.trace.artifact_contents[item] for item in identifiers]
            if sum(len(text.encode()) for text in texts) > 24576:
                return await self.gateway.record_host_block(
                    "host.delegate", arguments, "DELEGATION_INPUT_LIMIT"
                )
            if contains_protected(texts, self.protected_values):
                raise ContextError("DELEGATION_SENSITIVE_INPUT")
        except ContextError:
            return await self.gateway.record_host_block(
                "host.delegate", arguments, "DELEGATION_SENSITIVE_INPUT"
            )
        parent = self.gateway.grant.to_dict()
        grant = TaskGrant(
            parent
            | {
                "grant_id": new_id(),
                "subject_id": new_id(),
                "parent_grant_id": parent["grant_id"],
                "effects": ["file.read", "agent.delegate"] if role == "review" else ["file.read"],
                "resource_scopes": ["/workspace/" + ASSET_RESOURCE, BASELINE_RESOURCE]
                if role == "review"
                else [BASELINE_RESOURCE],
                "budgets": {
                    "tool_calls": 8 if role == "review" else 3,
                    "network_calls": 0,
                    "subagents": 1 if role == "review" else 0,
                },
            }
        )
        result, child = await self.gateway.spawn_child(grant, analysis_inputs=tuple(identifiers))
        if child is None:
            return result
        self.used = True
        node = {
            "role": role,
            "depth": self.depth + 1,
            "subject_id": grant.to_dict()["subject_id"],
            "parent_subject_id": parent["subject_id"],
            "grant": grant.to_dict(),
            "input_artifact_ids": list(identifiers),
            "status": "RUNNING",
            "started_at": utc_text(utc_now()),
            "finished_at": None,
            "output_artifact_id": None,
            "model_requests": 0,
            "stop_reason": None,
        }
        self.records.append(node)
        dispatched = child.trace.emit(
            "SUBAGENT_DISPATCHED",
            actor_id=parent["subject_id"],
            parents=[child._last_exposure_event],
            artifact_ids=list(identifiers),
            payload={
                "child_subject_id": node["subject_id"],
                "parent_subject_id": parent["subject_id"],
                "role": role,
                "depth": node["depth"],
                "grant_hash": sha(grant.to_dict()),
                "input_hashes": [
                    child.trace.artifacts[item].to_dict()["content_hash"] for item in identifiers
                ],
            },
        )
        child._last_exposure_event = dispatched
        protected = None
        try:
            # No factory invocation until explicit inputs, data policy and grants pass.
            protected = ProtectedModel(
                self.model_factory(),
                child,
                purpose="SUBAGENT",
                protected_values=self.protected_values,
                tokenizer=self.tokenizer,
                budget=self.budget.child(
                    grant.to_dict()["grant_id"],
                    max_requests=6 if role == "review" else 3,
                    max_units=120000 if role == "review" else 60000,
                ),
            )
            handler = (
                AnalysisDelegation(
                    child,
                    self.model_factory,
                    protected.budget,
                    protected_values=self.protected_values,
                    tokenizer=self.tokenizer,
                    depth=1,
                    records=self.records,
                    timeout=self.timeout,
                )
                if role == "review"
                else None
            )
            async with asyncio.timeout(self.timeout):
                output = await run_tool_agent(
                    protected,
                    child.proxy,
                    child,
                    "baseline" if role == "verify" else "alert",
                    task_profile="delegated-" + role,
                    task_inputs=tuple(identifiers),
                    delegation=handler,
                    max_model_calls=4 if role == "review" else 3,
                    max_tool_calls=4,
                )
            node["stop_reason"] = output["stop_reason"]
            artifact = output.get("final_artifact_id")
            if output["stop_reason"] != "MODEL_FINISHED" or artifact is None:
                raise ValueError("CHILD_TASK_INCOMPLETE")
            text = child.trace.artifact_contents[artifact]
            if len(text.encode()) > 8192:
                raise ValueError("CHILD_OUTPUT_INVALID")
            data = json.loads(text)
            keys = {"source_ip", "destination_ip", "classification"}
            if role == "review":
                keys |= {"asset", "verification_artifact_id"}
            if (
                not isinstance(data, dict)
                or set(data) != keys
                or any(
                    not isinstance(value, str) or not 1 <= len(value) <= 128
                    for value in data.values()
                )
                or data["classification"] not in {"expected", "unexpected"}
            ):
                raise ValueError("CHILD_OUTPUT_INVALID")
            read = any(
                event["actor_id"] == node["subject_id"]
                and event["event_type"] == "RESOURCE_READ"
                and child.trace.payloads[event["event_id"]].get("tool")
                == ("operations.read_file" if role == "review" else "evidence.read_alert")
                and any(
                    child.trace.artifacts[item].to_dict()["origin"]["source_id"]
                    == (
                        "operations.read_file:" + ASSET_RESOURCE
                        if role == "review"
                        else "evidence.read_alert:baseline"
                    )
                    for item in event["artifact_ids"]
                )
                for event in child.trace.events
            )
            if not read or (
                role == "review"
                and not any(
                    item["parent_subject_id"] == node["subject_id"]
                    and item["status"] == "FINISHED"
                    and item["output_artifact_id"] == data["verification_artifact_id"]
                    for item in self.records
                )
            ):
                raise ValueError("CHILD_TASK_INCOMPLETE")
            self.gateway.adopt_child_artifact(child, artifact)
            node.update(status="FINISHED", output_artifact_id=artifact)
            return {
                "ok": True,
                "decision": "ALLOW",
                "artifact_id": artifact,
                "content": text,
                "role": role,
                "subject_id": node["subject_id"],
            }
        except asyncio.CancelledError:
            node.update(status="CANCELLED", stop_reason="PARENT_CANCELLED")
            raise
        except TimeoutError:
            node.update(status="TIMED_OUT", stop_reason="CHILD_TIMEOUT")
        except (ModelProtocolError, ValueError) as error:
            code = str(error)
            node.update(
                status="FAILED",
                stop_reason=code
                if re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code)
                else "CHILD_OUTPUT_INVALID",
            )
        except Exception:
            node.update(status="FAILED", stop_reason="CHILD_RUN_FAILED")
        finally:
            node["finished_at"] = utc_text(utc_now())
            if protected is not None:
                node["model_requests"] = protected.forwarded_requests
                node["model_budget"] = protected.budget.view()
                node["egress"] = {
                    "blocked_requests": protected.blocked_requests,
                    "response_blocks": protected.response_blocks,
                }
            child.grant = TaskGrant(grant.to_dict() | {"status": "REVOKED"})
            node["grant_revoked"] = True
            child.trace.emit(
                "CONTENT_REGISTERED",
                actor_id=node["subject_id"],
                parents=[child._last_exposure_event],
                artifact_ids=[node["output_artifact_id"]] if node["output_artifact_id"] else [],
                payload={
                    "kind": "SUBAGENT_RUN_STATUS",
                    "status": node["status"],
                    "role": role,
                    "stop_reason": node["stop_reason"],
                    "grant_revoked": True,
                    "model_requests": node["model_requests"],
                },
            )
        return {"ok": False, "decision": "ALLOW", "code": node["stop_reason"], "role": role}
