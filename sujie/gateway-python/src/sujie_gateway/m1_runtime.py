"""M1 security hot path: deterministic authorization, effects, MCP mediation and trace."""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

from .contracts import (
    ApprovalRecord,
    DecisionRecord,
    SemanticAction,
    TaskContract,
    TaskGrant,
    canonical_json,
    load_json,
    snapshot_hash,
)
from .dsl import evaluate, load_rules
from .identifiers import new_id
from .invariants import approval_is_valid, check_clock, make_binding, scope_within


def policy_text(name: str = "m1.yaml") -> str:
    if name not in {"m1.yaml", "m2.yaml"}:
        raise ValueError("UNKNOWN_POLICY")
    return (Path(__file__).resolve().parents[2] / "policies" / name).read_text("utf-8")


def policy_snapshot_hash(name: str = "m1.yaml") -> str:
    return "sha256:" + hashlib.sha256(policy_text(name).encode("utf-8")).hexdigest()


def sha(value: Any) -> str:
    return snapshot_hash(value)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ToolSpec:
    qualified_name: str
    server_id: str
    server_name: str
    tool_name: str
    version_hash: str
    input_schema: dict[str, Any]


class ExecutionBlocked(RuntimeError):
    """Safe rejection after asynchronous discovery but before actual tool dispatch."""


class StdioMCPProxy:
    """Owns MCP processes and exposes only qualified, registry-pinned calls."""

    def __init__(self, servers: dict[str, StdioServerParameters]) -> None:
        self._params = servers
        self._clients: dict[str, Client] = {}
        self.registry: dict[str, ToolSpec] = {}
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "StdioMCPProxy":
        try:
            for alias, params in self._params.items():
                client = await self._stack.enter_async_context(
                    Client(params, raise_exceptions=True)
                )
                self._clients[alias] = client
                listed = await client.list_tools(cache_mode="reload")
                server = client.server_info
                server_name = server.name if server else alias
                server_version = server.version if server else "unknown"
                # M1 process-scoped identity. Persistent server enrollment belongs to M3.
                server_id = new_id()
                for tool in listed.tools:
                    qualified = f"{alias}.{tool.name}"
                    if qualified in self.registry:
                        raise RuntimeError("DUPLICATE_TOOL")
                    schema = tool.input_schema
                    version = sha(
                        {
                            "server": {"name": server_name, "version": server_version},
                            "tool": tool.model_dump(mode="json", by_alias=True),
                        }
                    )
                    self.registry[qualified] = ToolSpec(
                        qualified, server_id, server_name, tool.name, version, schema
                    )
            return self
        except BaseException:
            await self._stack.aclose()
            raise

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._stack.aclose()
        self._clients.clear()

    async def invoke(
        self,
        qualified_name: str,
        arguments: dict[str, Any],
        *,
        before_execute: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        spec = self.registry.get(qualified_name)
        if spec is None:
            raise RuntimeError("UNKNOWN_TOOL")
        # Re-read registration before every M1 call so drift never inherits old approval.
        current = await self._clients[qualified_name.split(".", 1)[0]].list_tools(
            cache_mode="reload"
        )
        match = next((tool for tool in current.tools if tool.name == spec.tool_name), None)
        if match is None:
            raise RuntimeError("TOOL_REMOVED")
        client = self._clients[qualified_name.split(".", 1)[0]]
        server = client.server_info
        observed = sha(
            {
                "server": {
                    "name": server.name if server else qualified_name.split(".", 1)[0],
                    "version": server.version if server else "unknown",
                },
                "tool": match.model_dump(mode="json", by_alias=True),
            }
        )
        if observed != spec.version_hash:
            raise RuntimeError("TOOL_VERSION_DRIFT")
        if before_execute is not None:
            # The gateway rechecks authority and consumes budget without yielding.
            before_execute()
        result = await self._clients[qualified_name.split(".", 1)[0]].call_tool(
            spec.tool_name, arguments=arguments
        )
        if result.is_error:
            raise RuntimeError("MCP_TOOL_ERROR")
        data = result.structured_content
        if not isinstance(data, dict):
            raise RuntimeError("UNSTRUCTURED_TOOL_RESULT")
        return data


def _logical_path(resource: str) -> str:
    if resource.startswith("/") or "\\" in resource or ".." in resource.split("/"):
        raise ValueError("INVALID_LOGICAL_RESOURCE")
    return "/workspace/" + resource


def semantic_action(
    qualified_name: str,
    arguments: dict[str, Any],
    spec: ToolSpec,
    contract: TaskContract,
    grant: TaskGrant,
    *,
    input_artifacts: list[str] | None = None,
) -> SemanticAction:
    """Map actual arguments and trusted executor configuration, never model labels."""
    if qualified_name == "evidence.read_alert":
        effect = (
            "file.read",
            "READ",
            [_logical_path(f"case-001/{arguments['alert_id']}.txt")],
            "NOT_APPLICABLE",
            False,
            True,
        )
    elif qualified_name == "operations.read_file":
        path = _logical_path(arguments["resource"])
        kind = "credential.read" if path.endswith("/secret.txt") else "file.read"
        effect = (kind, "READ", [path], "NOT_APPLICABLE", False, True)
    elif qualified_name == "operations.write_file":
        effect = (
            "file.write",
            "WRITE",
            [_logical_path(arguments["resource"])],
            "LOCAL",
            True,
            True,
        )
    elif qualified_name == "operations.send_data":
        # The label maps to a fixed hidden receiver URL in the controlled executor.
        if arguments["destination"] != "receiver":
            raise ValueError("UNKNOWN_DESTINATION")
        effect = (
            "data.transfer",
            "HTTP_POST",
            ["https://receiver.invalid/upload"],
            "UNTRUSTED_EXTERNAL",
            True,
            False,
        )
    else:
        raise ValueError("NO_EFFECT_ADAPTER")
    kind, operation, resources, trust, side_effect, reversible = effect
    c, g = contract.to_dict(), grant.to_dict()
    payload = {
        "schema_version": "1.0",
        "action_id": new_id(),
        "subject_id": g["subject_id"],
        "tool_identity": {
            "server_id": spec.server_id,
            "tool_name": spec.tool_name,
            "tool_version_hash": spec.version_hash,
        },
        "effect": {
            "kind": kind,
            "operation": operation,
            "resources": resources,
            "destination_trust": trust,
            "side_effect": side_effect,
            "reversible": reversible,
        },
        "input_artifacts": input_artifacts or [],
        "materialized_args_hash": sha(arguments),
        "contract_id": c["contract_id"],
        "grant_id": g["grant_id"],
    }
    return SemanticAction(payload)


@dataclass(frozen=True)
class GateDecision:
    decision: str
    hard_block: bool
    reason: str
    action: SemanticAction


@dataclass
class PendingApproval:
    """Server-side snapshot; arguments are never returned to the Agent."""

    decision: DecisionRecord
    action: SemanticAction
    tool: str
    arguments_json: str
    binding_json: str
    requested_event_id: str
    created_at: datetime
    expires_at: datetime
    approval: ApprovalRecord | None = None
    terminal_result: dict[str, Any] | None = None


class M1Policy:
    """Deterministic preconditions plus a typed, data-only M1 policy DSL."""

    def __init__(self, policy_name: str = "m1.yaml") -> None:
        text = policy_text(policy_name)
        self.rules = load_rules(text)
        self.snapshot_hash = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    def decide(
        self,
        action: SemanticAction,
        contract: TaskContract,
        grant: TaskGrant,
        *,
        now: datetime | None = None,
        contract_usage: dict[str, int] | None = None,
        grant_usage: dict[str, int] | None = None,
        data_facts: dict[str, Any] | None = None,
    ) -> GateDecision:
        a, c, g = action.to_dict(), contract.to_dict(), grant.to_dict()
        kind, resources = a["effect"]["kind"], a["effect"]["resources"]
        if c["status"] != "ACTIVE" or g["status"] != "ACTIVE":
            return GateDecision("BLOCK", True, "GRANT_INVALID", action)
        current = now if now is not None else utc_now()
        check_clock(current)
        if current >= min(
            datetime.fromisoformat(c["expires_at"]), datetime.fromisoformat(g["expires_at"])
        ):
            return GateDecision("BLOCK", True, "GRANT_EXPIRED", action)
        if (
            a["contract_id"] != c["contract_id"]
            or g["contract_id"] != c["contract_id"]
            or a["grant_id"] != g["grant_id"]
            or a["subject_id"] != g["subject_id"]
        ):
            return GateDecision("BLOCK", True, "GRANT_MISMATCH", action)
        granted = kind in g["effects"] or (
            kind == "file.write"
            and "file.write:report" in g["effects"]
            and all("/output/" in resource for resource in resources)
        )
        if not granted:
            return GateDecision("BLOCK", False, "EFFECT_NOT_GRANTED", action)
        if any(
            not any(scope_within(resource, scope) for scope in g["resource_scopes"])
            for resource in resources
        ):
            return GateDecision("BLOCK", True, "RESOURCE_OUT_OF_SCOPE", action)
        forbidden = set(c["forbidden_effects"])
        external_transfer = kind == "data.transfer" and a["effect"]["destination_trust"] in {
            "TRUSTED_EXTERNAL",
            "UNTRUSTED_EXTERNAL",
        }
        if kind in forbidden or (external_transfer and "external.data_transfer" in forbidden):
            return GateDecision("BLOCK", True, "CONTRACT_FORBIDS_EFFECT", action)
        permitted = any(
            item["kind"] == kind
            and all(
                scope_within(resource, item["resource"])
                if resource.startswith("/")
                else resource == item["resource"]
                for resource in resources
            )
            for item in c["allowed_effects"]
        )
        if not permitted:
            return GateDecision("BLOCK", False, "EFFECT_OUTSIDE_CONTRACT", action)
        for document, usage in ((c, contract_usage or {}), (g, grant_usage or {})):
            if any(
                usage.get(dimension, 0) + cost > document["budgets"].get(dimension, 0)
                for dimension, cost in execution_cost(action).items()
            ):
                return GateDecision("BLOCK", True, "BUDGET_EXHAUSTED", action)
        outcome, matched = evaluate(
            self.rules,
            {
                "runtime": {"prerequisites_passed": True},
                "action": {"effect": a["effect"]},
                "data": data_facts or {},
            },
        )
        translated = {"allow": "ALLOW", "ask": "ASK", "block": "BLOCK", "hard_block": "BLOCK"}
        decision = translated[outcome]
        return GateDecision(
            decision, outcome == "hard_block", matched[-1] if matched else "NO_RULE", action
        )


def execution_cost(action: SemanticAction) -> dict[str, int]:
    """M1 counts dispatch attempts, including failures, rather than proposals or replays."""
    cost = {"tool_calls": 1}
    if action.to_dict()["effect"]["kind"] == "data.transfer":
        cost["network_calls"] = 1
    return cost


class TraceLedger:
    """M1 in-memory append-only trace. M2 will add Artifact edges and persistence."""

    def __init__(self, contract: TaskContract) -> None:
        self._contract = contract.to_dict()
        self.trace_id = new_id()
        self.events: list[dict[str, Any]] = []

    def emit(
        self,
        event_type: str,
        *,
        actor_id: str,
        parents: list[str] | None = None,
        action_id: str | None = None,
        decision_id: str | None = None,
        payload: dict[str, Any] | None = None,
        artifact_ids: list[str] | None = None,
    ) -> str:
        event_id = new_id()
        body = payload or {}
        self.events.append(
            {
                "schema_version": "1.0",
                "event_id": event_id,
                "trace_id": self.trace_id,
                "parent_event_ids": parents or [],
                "event_type": event_type,
                "actor_id": actor_id,
                "session_id": self._contract["session_id"],
                "contract_id": self._contract["contract_id"],
                "artifact_ids": list(artifact_ids or []),
                "action_id": action_id,
                "decision_id": decision_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "sequence": len(self.events),
                "payload_ref": f"evidence://trace/{event_id}",
                "payload_hash": sha(body),
            }
        )
        return event_id


class M1Gateway:
    def __init__(self, proxy: StdioMCPProxy, contract: TaskContract, grant: TaskGrant) -> None:
        self.proxy, self.contract, self.grant = proxy, contract, grant
        self.policy = M1Policy()
        self.trace = TraceLedger(contract)
        self._pending: dict[str, PendingApproval] = {}
        self._approval_lock = asyncio.Lock()
        self._contract_usage: dict[str, dict[str, int]] = {}
        self._grant_usage: dict[str, dict[str, int]] = {}
        for spec in proxy.registry.values():
            self.trace.emit(
                "TOOL_REGISTERED",
                actor_id=spec.server_id,
                payload={"qualified_name": spec.qualified_name, "version_hash": spec.version_hash},
            )

    def _make_action(
        self, tool: str, arguments: dict[str, Any], *, input_artifacts: list[str] | None = None
    ) -> SemanticAction:
        return semantic_action(
            tool,
            arguments,
            self.proxy.registry[tool],
            self.contract,
            self.grant,
            input_artifacts=input_artifacts,
        )

    def _input_hashes(self, action: SemanticAction) -> tuple[str, str]:
        return sha([]), sha([])

    def _record_decision(
        self, action: SemanticAction, decision: GateDecision, decision_id: str
    ) -> None:
        pass

    def _after_result(
        self,
        action: SemanticAction,
        tool: str,
        arguments: dict[str, Any],
        data: dict[str, Any],
        event_id: str,
    ) -> dict[str, Any]:
        return {}

    def _decide(self, action: SemanticAction) -> GateDecision:
        return self.policy.decide(
            action,
            self.contract,
            self.grant,
            contract_usage=self._contract_usage.get(self.contract.to_dict()["contract_id"], {}),
            grant_usage=self._grant_usage.get(self.grant.to_dict()["grant_id"], {}),
        )

    def _reserve_execution(
        self,
        action: SemanticAction,
        expected: str,
        parent: str,
        decision_id: str,
        *,
        pending: PendingApproval | None = None,
    ) -> None:
        """Atomic on this gateway's event loop: no await between recheck and reservation."""
        decision = self._decide(action)
        a = action.to_dict()
        permitted = decision.decision == expected
        reason = decision.reason
        input_hash, provenance_hash = self._input_hashes(action)
        if pending is not None and (
            pending.approval is None
            or not approval_is_valid(
                pending.approval,
                pending.decision,
                action,
                self.contract,
                self.grant,
                now=utc_now(),
                input_content_hash=input_hash,
                provenance_snapshot_hash=provenance_hash,
            )
        ):
            permitted, reason = False, "APPROVAL_STALE"
        self.trace.emit(
            "COMMIT_CHECKED",
            actor_id=a["subject_id"],
            parents=[parent],
            action_id=a["action_id"],
            decision_id=decision_id,
            artifact_ids=a["input_artifacts"],
            payload={"binding_valid": permitted, "reason": reason},
        )
        if not permitted:
            raise ExecutionBlocked(reason)
        for ledger, key in (
            (self._contract_usage, a["contract_id"]),
            (self._grant_usage, a["grant_id"]),
        ):
            usage = ledger.setdefault(key, {})
            for dimension, cost in execution_cost(action).items():
                usage[dimension] = usage.get(dimension, 0) + cost

    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        actor = self.grant.to_dict()["subject_id"]
        proposed = self.trace.emit("TOOL_PROPOSED", actor_id=actor, payload={"tool": tool})
        try:
            # Bind and execute an owned copy, not a caller-mutated dictionary after an await.
            args = load_json(canonical_json(args))
            action = self._make_action(tool, args)
        except (KeyError, TypeError, ValueError):
            self.trace.emit(
                "TOOL_CALL_DECIDED",
                actor_id=actor,
                parents=[proposed],
                payload={"decision": "BLOCK", "reason": "INVALID_ACTION"},
            )
            return {"ok": False, "decision": "BLOCK", "code": "INVALID_ACTION"}
        decision = self._decide(action)
        decision_id = new_id()
        self._record_decision(action, decision, decision_id)
        reason_code = re.sub(r"[^A-Z0-9_]", "_", decision.reason.upper())[:96]
        decision_record = DecisionRecord(
            {
                "schema_version": "1.0",
                "decision_id": decision_id,
                "action_id": action.to_dict()["action_id"],
                "decision": decision.decision,
                "hard_block": decision.hard_block,
                "risk": "LOW" if decision.decision == "ALLOW" else "HIGH",
                "uncertainty": 0.0,
                "reason_codes": [reason_code],
                "matched_facts": [],
                "policy_snapshot_hash": self.contract.to_dict()["policy_snapshot_hash"],
                "contract_id": self.contract.to_dict()["contract_id"],
                "grant_id": self.grant.to_dict()["grant_id"],
                "timestamp": utc_text(utc_now()),
            }
        )
        decided = self.trace.emit(
            "TOOL_CALL_DECIDED",
            actor_id=actor,
            parents=[proposed],
            action_id=action.to_dict()["action_id"],
            decision_id=decision_id,
            artifact_ids=action.to_dict()["input_artifacts"],
            payload={"decision": decision.decision, "reason": decision.reason},
        )
        if decision.decision == "ASK":
            now = utc_now()
            input_hash, provenance_hash = self._input_hashes(action)
            requested = self.trace.emit(
                "APPROVAL_REQUESTED",
                actor_id=actor,
                parents=[decided],
                action_id=action.to_dict()["action_id"],
                decision_id=decision_id,
                payload={"expires_in_seconds": 300},
            )
            binding_json = canonical_json(
                make_binding(
                    action,
                    self.contract,
                    self.grant,
                    input_content_hash=input_hash,
                    provenance_snapshot_hash=provenance_hash,
                )
            )
            async with self._approval_lock:
                self._pending[decision_id] = PendingApproval(
                    decision=decision_record,
                    action=action,
                    tool=tool,
                    arguments_json=canonical_json(args),
                    binding_json=binding_json,
                    requested_event_id=requested,
                    created_at=now,
                    expires_at=now + timedelta(minutes=5),
                )
        if decision.decision != "ALLOW":
            return {
                "ok": False,
                "decision": decision.decision,
                "code": decision.reason,
                "decision_id": decision_id,
                "allowed_alternatives": ["write_local_report"]
                if decision.decision == "BLOCK"
                else [],
            }
        try:
            result = await self.proxy.invoke(
                tool,
                args,
                before_execute=lambda: self._reserve_execution(
                    action, "ALLOW", decided, decision_id
                ),
            )
        except ExecutionBlocked as error:
            self.trace.emit(
                "TOOL_CALL_DECIDED",
                actor_id=actor,
                parents=[decided],
                action_id=action.to_dict()["action_id"],
                decision_id=decision_id,
                payload={"decision": "BLOCK", "reason": str(error)},
            )
            return {
                "ok": False,
                "decision": "BLOCK",
                "code": str(error),
                "decision_id": decision_id,
            }
        except RuntimeError as error:
            self.trace.emit(
                "EXECUTION_RESULT",
                actor_id=actor,
                parents=[decided],
                action_id=action.to_dict()["action_id"],
                decision_id=decision_id,
                payload={"tool": tool, "ok": False, "code": str(error)},
            )
            return {"ok": False, "decision": "ALLOW", "code": "TOOL_EXECUTION_FAILED"}
        executed = self.trace.emit(
            "EXECUTION_RESULT",
            actor_id=actor,
            parents=[decided],
            action_id=action.to_dict()["action_id"],
            decision_id=decision_id,
            artifact_ids=action.to_dict()["input_artifacts"],
            payload={"tool": tool, "ok": True},
        )
        try:
            metadata = self._after_result(action, tool, args, result, executed)
        except ValueError:
            return {"ok": False, "decision": "ALLOW", "code": "PROVENANCE_RESULT_REJECTED"}
        return {"ok": True, "decision": "ALLOW", "data": result, **metadata}

    async def approve(self, decision_id: str, principal_id: str) -> dict[str, Any]:
        """Trusted control-plane entry point; it is deliberately not an Agent tool."""
        async with self._approval_lock:
            pending = self._pending.get(decision_id)
            now = utc_now()
            if pending is None:
                return {"ok": False, "code": "APPROVAL_NOT_FOUND"}
            if pending.terminal_result is not None:
                return {"ok": False, "code": "APPROVAL_ALREADY_TERMINAL"}
            if pending.approval is not None:
                return {"ok": True, "code": "ALREADY_APPROVED"}
            contract = self.contract.to_dict()
            if principal_id != contract["principal_id"]:
                return {"ok": False, "code": "APPROVER_MISMATCH"}
            if now >= pending.expires_at:
                return {"ok": False, "code": "APPROVAL_EXPIRED"}
            input_hash, provenance_hash = self._input_hashes(pending.action)
            if self._decide(pending.action).decision != "ASK":
                return {"ok": False, "code": "APPROVAL_STALE"}
            binding = make_binding(
                pending.action,
                self.contract,
                self.grant,
                input_content_hash=input_hash,
                provenance_snapshot_hash=provenance_hash,
            )
            if canonical_json(binding) != pending.binding_json:
                return {"ok": False, "code": "APPROVAL_STALE"}
            approval = ApprovalRecord(
                {
                    "schema_version": "1.0",
                    "approval_id": new_id(),
                    "decision_id": decision_id,
                    "approved_by": principal_id,
                    "binding": binding,
                    "status": "APPROVED",
                    "created_at": utc_text(pending.created_at),
                    "approved_at": utc_text(now),
                    "expires_at": utc_text(pending.expires_at),
                    "consumed": False,
                }
            )
            pending.approval = approval
            self.trace.emit(
                "APPROVAL_RECORDED",
                actor_id=principal_id,
                parents=[pending.requested_event_id],
                action_id=pending.action.to_dict()["action_id"],
                decision_id=decision_id,
                payload={"approval_id": approval.to_dict()["approval_id"]},
            )
            return {
                "ok": True,
                "approval_id": approval.to_dict()["approval_id"],
                "decision_id": decision_id,
            }

    async def commit(self, decision_id: str) -> dict[str, Any]:
        """Atomically validate and consume an approved ASK before one side effect."""
        async with self._approval_lock:
            pending = self._pending.get(decision_id)
            if pending is None:
                return {"ok": False, "code": "APPROVAL_NOT_FOUND"}
            if pending.terminal_result is not None:
                return {**pending.terminal_result, "replayed": True}
            if pending.approval is None:
                return {"ok": False, "code": "APPROVAL_REQUIRED"}
            now = utc_now()
            input_hash, provenance_hash = self._input_hashes(pending.action)
            if not approval_is_valid(
                pending.approval,
                pending.decision,
                pending.action,
                self.contract,
                self.grant,
                now=now,
                input_content_hash=input_hash,
                provenance_snapshot_hash=provenance_hash,
            ):
                return {"ok": False, "code": "APPROVAL_STALE"}

            arguments = load_json(pending.arguments_json)
            try:
                fresh = self._make_action(
                    pending.tool,
                    arguments,
                    input_artifacts=pending.action.to_dict()["input_artifacts"],
                )
            except (KeyError, TypeError, ValueError):
                return {"ok": False, "code": "APPROVAL_STALE"}
            fresh_body = fresh.to_dict()
            fresh_body["action_id"] = pending.action.to_dict()["action_id"]
            if sha(fresh_body) != sha(pending.action.to_dict()):
                return {"ok": False, "code": "APPROVAL_STALE"}
            fresh = SemanticAction(fresh_body)
            if self._decide(fresh).decision != "ASK":
                return {"ok": False, "code": "APPROVAL_STALE"}

            checked = self.trace.emit(
                "COMMIT_CHECKED",
                actor_id=self.grant.to_dict()["subject_id"],
                parents=[pending.requested_event_id],
                action_id=pending.action.to_dict()["action_id"],
                decision_id=decision_id,
                payload={"binding_valid": True},
            )
            try:
                data = await self.proxy.invoke(
                    pending.tool,
                    arguments,
                    before_execute=lambda: self._reserve_execution(
                        pending.action, "ASK", checked, decision_id, pending=pending
                    ),
                )
                result = {
                    "ok": True,
                    "decision": "ASK",
                    "approved": True,
                    "data": data,
                    "replayed": False,
                }
            except ExecutionBlocked as error:
                result = {
                    "ok": False,
                    "decision": "BLOCK",
                    "approved": True,
                    "code": str(error),
                    "replayed": False,
                }
            except RuntimeError:
                result = {
                    "ok": False,
                    "decision": "ASK",
                    "approved": True,
                    "code": "TOOL_EXECUTION_FAILED",
                    "replayed": False,
                }
            approval_body = pending.approval.to_dict()
            approval_body["consumed"] = True
            pending.approval = ApprovalRecord(approval_body)
            pending.terminal_result = result
            executed = self.trace.emit(
                "EXECUTION_RESULT",
                actor_id=self.grant.to_dict()["subject_id"],
                parents=[checked],
                action_id=pending.action.to_dict()["action_id"],
                decision_id=decision_id,
                artifact_ids=pending.action.to_dict()["input_artifacts"],
                payload={"tool": pending.tool, "ok": result["ok"]},
            )
            if result["ok"]:
                try:
                    result.update(
                        self._after_result(pending.action, pending.tool, arguments, data, executed)
                    )
                except ValueError:
                    result = {
                        "ok": False,
                        "decision": "ASK",
                        "approved": True,
                        "code": "PROVENANCE_RESULT_REJECTED",
                        "replayed": False,
                    }
                    pending.terminal_result = result
            return result
