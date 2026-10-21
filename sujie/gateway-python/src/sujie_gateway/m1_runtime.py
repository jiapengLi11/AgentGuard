"""M1 security hot path: deterministic authorization, effects, MCP mediation and trace."""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import sqlite3
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

from .alignment import explain_alignment
from .contracts import (
    ApprovalRecord,
    DecisionRecord,
    DetectionFinding,
    ProvenanceEnvelope,
    SemanticAction,
    TaskContract,
    TaskGrant,
    canonical_json,
    load_json,
    local_scope,
    snapshot_hash,
)
from .detection_v2 import normalized_view as document_normalized_view
from .detector import ScanLimitExceeded, get_detector
from .doc_parsing import scan_document, tool_documents
from .dsl import evaluate, load_rules
from .execution_policy import ExecutionPolicy
from .git_policy import GitPolicy
from .invariants import (
    InvariantViolation,
    approval_is_valid,
    assert_child_within_parent,
    make_binding,
    scope_within,
)
from .memory_detection import deferred_memory_finding
from .memory_policy import MemoryPolicy
from .model_context import contains_protected, safe_path
from .network_policy import NetworkPolicy, payload_values
from .sanitization import extract_public_ipv4_iocs, render_public_ipv4_iocs
from .sensitive_targets import sensitive_write_target
from .tool_result import ToolResultError, ToolResultSnapshot, snapshot_tool_result

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
LOCAL_TOOL_CATALOG = {
    "evidence": frozenset({"read_alert"}),
    "operations": frozenset({"read_file", "write_file", "exec_hash_report", "send_data"}),
    "memory": frozenset({"read", "write"}),
    "git": frozenset({"push_report"}),
    "network": frozenset({"fetch"}),
    "execution": frozenset({"run"}),
    "git_delivery": frozenset({"inspect", "state", "push"}),
}


def new_id() -> str:
    value = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), "big")
    return "".join(CROCKFORD[(value >> (5 * (25 - i))) & 31] for i in range(26))


def sha(value: Any) -> str:
    return snapshot_hash(value)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Runtime detector: extended (detection_v2) by default, SUJIE_DETECTOR=frozen for rules-v0.3.
ACTIVE_DETECTOR = get_detector()
DETECTOR_VERSION = ACTIVE_DETECTOR.DETECTOR_VERSION
detect_indirect = ACTIVE_DETECTOR.detect_indirect
normalized_view = ACTIVE_DETECTOR.normalized_view


def utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class ResultScanRejected(RuntimeError):
    """A tool result contained text the detector could not completely scan."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ToolSpec:
    qualified_name: str
    server_id: str
    server_name: str
    tool_name: str
    version_hash: str
    input_schema: dict[str, Any]
    server_version: str = "unknown"


class StdioMCPProxy:
    """Owns MCP processes and exposes only qualified, registry-pinned calls."""

    def __init__(
        self,
        servers: dict[str, StdioServerParameters],
        *,
        expected_tools: dict[str, frozenset[str]] | None = None,
    ) -> None:
        if expected_tools is not None and set(expected_tools) != set(servers):
            raise ValueError("INCOMPLETE_TOOL_CATALOG")
        self._params = servers
        self._expected_tools = (
            {alias: frozenset(names) for alias, names in expected_tools.items()}
            if expected_tools is not None
            else None
        )
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
                if self._expected_tools is not None:
                    names = [tool.name for tool in listed.tools]
                    if len(names) != len(set(names)) or set(names) != self._expected_tools[alias]:
                        raise RuntimeError("TOOL_CATALOG_DRIFT")
                server = client.server_info
                server_name = server.name if server else alias
                server_version = server.version if server else "unknown"
                # M1 process-scoped identity. Persistent server enrollment belongs to M3.
                server_id = new_id()
                for tool in listed.tools:
                    metadata = tool.model_dump(mode="json", by_alias=True)
                    serialized = canonical_json(metadata)
                    if len(serialized) > 100_000:
                        raise RuntimeError("TOOL_METADATA_TOO_LARGE")
                    _, metadata_finding = detect_indirect(serialized, new_id(), new_id())
                    if metadata_finding is not None:
                        raise RuntimeError("TOOL_METADATA_INJECTION")
                    qualified = f"{alias}.{tool.name}"
                    if qualified in self.registry:
                        raise RuntimeError("DUPLICATE_TOOL")
                    schema = tool.input_schema
                    version = sha(
                        {
                            "server": {"name": server_name, "version": server_version},
                            "tool": metadata,
                        }
                    )
                    self.registry[qualified] = ToolSpec(
                        qualified,
                        server_id,
                        server_name,
                        tool.name,
                        version,
                        schema,
                        server_version,
                    )
            return self
        except BaseException:
            await self._stack.aclose()
            raise

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._stack.aclose()
        self._clients.clear()

    async def invoke(self, qualified_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self.registry.get(qualified_name)
        if spec is None:
            raise RuntimeError("UNKNOWN_TOOL")
        # Re-read registration before every M1 call so drift never inherits old approval.
        current = await self._clients[qualified_name.split(".", 1)[0]].list_tools(
            cache_mode="reload"
        )
        if self._expected_tools is not None:
            alias = qualified_name.split(".", 1)[0]
            names = [tool.name for tool in current.tools]
            if len(names) != len(set(names)) or set(names) != self._expected_tools[alias]:
                raise RuntimeError("TOOL_CATALOG_DRIFT")
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
    sensitive_resources: tuple[str, ...] = ("/workspace/case-001/secret.txt",),
    network_policy: NetworkPolicy | None = None,
    execution_policy: ExecutionPolicy | None = None,
    git_policy: GitPolicy | None = None,
    memory_policy: MemoryPolicy | None = None,
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
        kind = (
            "credential.read"
            if any(scope_within(path, scope) for scope in sensitive_resources)
            else "file.read"
        )
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
    elif qualified_name == "operations.exec_hash_report":
        resource = arguments["resource"]
        if not isinstance(resource, str) or not resource.startswith("case-001/output/"):
            raise ValueError("INVALID_EXEC_RESOURCE")
        effect = (
            "exec",
            "SPAWN_FIXED_HASH_WORKER",
            [_logical_path(resource)],
            "LOCAL",
            True,
            False,
        )
    elif qualified_name == "execution.run":
        if execution_policy is None or spec.server_version != execution_policy.server_version:
            raise ValueError("EXEC_POLICY_BINDING_INVALID")
        request = execution_policy.inspect(arguments)
        operation = request["operation"]
        if any(scope_within(request["resource"], scope) for scope in sensitive_resources):
            operation = "EXEC_REJECT_RESOURCE"
        effect = ("exec", operation, [request["resource"]], "LOCAL", True, False)
    elif qualified_name in {"git_delivery.inspect", "git_delivery.state", "git_delivery.push"}:
        if git_policy is None or spec.server_version != git_policy.server_version:
            raise ValueError("GIT_POLICY_BINDING_INVALID")
        if qualified_name == "git_delivery.push":
            request = git_policy.inspect(arguments)
            effect = ("git.push", request["operation"], [request["resource"]], "LOCAL", True, False)
        else:
            if arguments:
                raise ValueError("GIT_ARGUMENTS_INVALID")
            effect = (
                "file.read",
                "INSPECT_PINNED_GIT" if qualified_name.endswith("inspect") else "READ_GIT_STATE",
                ["/workspace/case-001/repository-review"],
                "LOCAL",
                False,
                True,
            )
    elif qualified_name == "git.push_report":
        if arguments:
            raise ValueError("INVALID_GIT_ARGUMENTS")
        effect = (
            "git.push",
            "PUSH_FIXED_LOCAL_REF",
            ["/workspace/case-001/remote.git/refs/heads/report"],
            "LOCAL",
            True,
            False,
        )
    elif qualified_name == "host.delegate":
        effect = (
            "agent.delegate",
            "SPAWN_ANALYSIS_AGENT"
            if arguments.get("analysis_only") is True
            else "SPAWN_CHILD_GATEWAY",
            arguments["analysis_resources"]
            if arguments.get("analysis_only") is True
            else ["/workspace/case-001"],
            "LOCAL",
            True,
            False,
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
    elif qualified_name in {"memory.read", "memory.write"}:
        key = arguments["key"]
        if not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key) is None:
            raise ValueError("INVALID_MEMORY_KEY")
        writing = qualified_name == "memory.write"
        operation = "STORE_EVIDENCE" if writing else "READ"
        if memory_policy is not None:
            if spec.server_version != memory_policy.server_version:
                raise ValueError("MEMORY_POLICY_BINDING_INVALID")
            operation = memory_policy.inspect(writing, arguments)["operation"]
        effect = (
            "memory.write" if writing else "memory.read",
            operation,
            [_logical_path(f"case-001/memory/{key}")],
            "LOCAL" if writing else "NOT_APPLICABLE",
            writing,
            True,
        )
    elif qualified_name == "network.fetch":
        if network_policy is None or spec.server_version != network_policy.server_version:
            raise ValueError("NETWORK_POLICY_BINDING_INVALID")
        request = network_policy.validate_request(arguments)
        transfer = request["transfer"]
        effect = (
            "data.transfer" if transfer else "file.read",
            "NET_FETCH_" + request["method"],
            [request["origin"] + "/"],
            "TRUSTED_EXTERNAL"
            if request["origin"] in network_policy.to_dict()["trusted_origins"]
            else "UNTRUSTED_EXTERNAL",
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
    input_content_hash: str
    provenance_snapshot_hash: str
    requested_event_id: str
    created_at: datetime
    expires_at: datetime
    approval: ApprovalRecord | None = None
    terminal_result: dict[str, Any] | None = None
    review_metadata: dict | None = None
    result_artifacts: tuple[str, ...] = ()


class M1Policy:
    """Deterministic preconditions plus a typed, data-only M1 policy DSL."""

    EFFECT_PURPOSE = {
        "file.read": "READ",
        "credential.read": "READ",
        "memory.read": "READ",
        "file.write": "WRITE_REPORT",
        "memory.write": "STORE_EVIDENCE",
        "data.transfer": "TRANSFER",
        "external.data_transfer": "TRANSFER",
        "exec": "EXECUTE",
        "git.push": "EXECUTE",
        "agent.delegate": "DELEGATE",
    }

    def __init__(self) -> None:
        policy = Path(__file__).resolve().parents[2] / "policies" / "m1.yaml"
        source = policy.read_bytes()
        self.snapshot_hash = "sha256:" + hashlib.sha256(source).hexdigest()
        self.rules = load_rules(source.decode("utf-8"))

    def decide(
        self, action: SemanticAction, contract: TaskContract, grant: TaskGrant
    ) -> GateDecision:
        a, c, g = action.to_dict(), contract.to_dict(), grant.to_dict()
        kind, resources = a["effect"]["kind"], a["effect"]["resources"]
        if c["status"] != "ACTIVE" or g["status"] != "ACTIVE":
            return GateDecision("BLOCK", True, "GRANT_INVALID", action)
        if utc_now() >= min(
            datetime.fromisoformat(c["expires_at"]),
            datetime.fromisoformat(g["expires_at"]),
        ):
            return GateDecision("BLOCK", True, "GRANT_EXPIRED", action)
        if c["policy_snapshot_hash"] != self.snapshot_hash:
            return GateDecision("BLOCK", True, "POLICY_SNAPSHOT_MISMATCH", action)
        if a["contract_id"] != c["contract_id"] or a["grant_id"] != g["grant_id"]:
            return GateDecision("BLOCK", True, "GRANT_MISMATCH", action)
        if kind == "file.write" and any(sensitive_write_target(r) for r in resources):
            # Hard deny before any grant/contract widening or approval can apply.
            return GateDecision("BLOCK", True, "SENSITIVE_TARGET_FORBIDDEN", action)
        granted = kind in g["effects"] or (
            kind == "file.write"
            and "file.write:report" in g["effects"]
            and all("/output/" in resource for resource in resources)
        )
        if not granted:
            return GateDecision("BLOCK", False, "EFFECT_NOT_GRANTED", action)
        if a["effect"]["operation"].startswith("NET_FETCH_") and any(
            resource not in g["resource_scopes"] for resource in resources
        ):
            return GateDecision("BLOCK", True, "RESOURCE_OUT_OF_SCOPE", action)
        if any(
            not any(scope_within(resource, scope) for scope in g["resource_scopes"])
            for resource in resources
            if resource.startswith("/")
        ):
            return GateDecision("BLOCK", True, "RESOURCE_OUT_OF_SCOPE", action)
        forbidden = set(c["forbidden_effects"])
        if kind in forbidden or (kind == "data.transfer" and "external.data_transfer" in forbidden):
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
        required_purpose = self.EFFECT_PURPOSE.get(kind)
        if required_purpose is None or required_purpose not in c["allowed_purposes"]:
            return GateDecision("BLOCK", True, "PURPOSE_NOT_ALLOWED", action)
        outcome, matched = evaluate(
            self.rules,
            {
                "runtime": {"prerequisites_passed": True},
                "action": {"effect": a["effect"]},
            },
        )
        translated = {"allow": "ALLOW", "ask": "ASK", "block": "BLOCK", "hard_block": "BLOCK"}
        decision = translated[outcome]
        return GateDecision(
            decision, outcome == "hard_block", matched[-1] if matched else "NO_RULE", action
        )


class TraceLedger:
    """Append-only events and evidence; optional SQLite durability is control-plane only."""

    def __init__(
        self,
        contract: TaskContract,
        db_path: Path | None = None,
        *,
        workspace_identity: str = "synthetic-workspace",
    ) -> None:
        self._contract = contract.to_dict()
        self._workspace_identity = workspace_identity
        self.trace_id = new_id()
        self.events: list[dict[str, Any]] = []
        self._event_ids: set[str] = set()
        self._events_by_id: dict[str, dict[str, Any]] = {}
        self.payloads: dict[str, dict[str, Any]] = {}
        self.artifacts: dict[str, ProvenanceEnvelope] = {}
        self.artifact_contents: dict[str, str] = {}
        self.normalized_views: dict[str, str] = {}
        self.file_provenance: dict[str, tuple[str, list[str]]] = {}
        self._db: sqlite3.Connection | None = None
        if db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(db_path)
            # Keep per-record commits; reuse the rollback journal without directory churn.
            # EXTRA preserves durable rollback journaling. No asynchronous evidence buffer.
            mode = self._db.execute("PRAGMA journal_mode=TRUNCATE").fetchone()[0]
            self._db.execute("PRAGMA synchronous=EXTRA")
            if mode != "truncate" or self._db.execute("PRAGMA synchronous").fetchone()[0] != 3:
                self.close()
                raise RuntimeError("TRACE_DURABILITY_CONFIGURATION_FAILED")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS trace_events "
                "(event_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, event_json TEXT NOT NULL, payload_json TEXT NOT NULL)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS artifacts "
                "(artifact_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, envelope_json TEXT NOT NULL, content TEXT NOT NULL)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS normalized_views "
                "(artifact_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, content TEXT NOT NULL)"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS file_provenance "
                "(workspace_identity TEXT NOT NULL, resource TEXT NOT NULL, "
                "content_hash TEXT NOT NULL, source_ids_json TEXT NOT NULL, "
                "PRIMARY KEY (workspace_identity, resource))"
            )
            self._db.commit()
            for artifact_id, envelope_json, content in self._db.execute(
                "SELECT artifact_id, envelope_json, content FROM artifacts"
            ):
                self.artifacts[artifact_id] = ProvenanceEnvelope(load_json(envelope_json))
                self.artifact_contents[artifact_id] = content
            for resource, content_hash, source_ids_json in self._db.execute(
                "SELECT resource, content_hash, source_ids_json FROM file_provenance "
                "WHERE workspace_identity = ?",
                (self._workspace_identity,),
            ):
                self.file_provenance[resource] = (content_hash, load_json(source_ids_json))

    def close(self) -> None:
        """Release the optional evidence database at the owning runtime's shutdown."""
        if self._db is not None:
            self._db.close()
            self._db = None

    def create_artifact(
        self,
        content: str,
        *,
        source_event_id: str,
        source_id: str,
        confidentiality: str = "INTERNAL",
        parents: list[str] | None = None,
        origin_type: str = "MCP_TOOL_RESULT",
        authority: str = "DATA_ONLY",
    ) -> str:
        if authority not in {"DATA_ONLY", "USER_REQUEST"} or (
            authority == "USER_REQUEST" and (origin_type != "USER_MESSAGE" or parents)
        ):
            raise ValueError("INVALID_ARTIFACT_AUTHORITY")
        if source_event_id not in self._event_ids or any(
            parent not in self.artifacts for parent in (parents or [])
        ):
            raise ValueError("UNKNOWN_PROVENANCE_PARENT")
        artifact_id = new_id()
        parent_bodies = [self.artifacts[parent].to_dict() for parent in (parents or [])]
        confidentiality_order = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "SECRET")
        if parent_bodies:
            confidentiality = max(
                [confidentiality, *(body["confidentiality"] for body in parent_bodies)],
                key=confidentiality_order.index,
            )
        allowed = {"READ", "ANALYZE", "QUOTE", "WRITE_REPORT", "STORE_EVIDENCE"}
        forbidden = {"AUTHORIZE", "EXECUTE", "CHANGE_POLICY", "TRANSFER", "DELEGATE"}
        for body in parent_bodies:
            allowed.intersection_update(body["allowed_uses"])
            forbidden.update(body["forbidden_uses"])
        allowed.difference_update(forbidden)
        envelope = ProvenanceEnvelope(
            {
                "schema_version": "1.0",
                "artifact_id": artifact_id,
                "content_ref": f"evidence://artifact/{artifact_id}",
                "content_hash": sha(content),
                "origin": {
                    "type": origin_type,
                    "source_id": source_id,
                    "event_id": source_event_id,
                },
                "authority": authority,
                "integrity": "UNTRUSTED",
                "confidentiality": confidentiality,
                "allowed_uses": sorted(allowed),
                "forbidden_uses": sorted(forbidden),
                "parents": parents or [],
                "transformations": [],
                "source_spans": [
                    {
                        "source_start": 0,
                        "source_end": len(content),
                        "view_start": 0,
                        "view_end": len(content),
                    }
                ],
                "created_at": utc_text(utc_now()),
            }
        )
        self.artifacts[artifact_id] = envelope
        self.artifact_contents[artifact_id] = content
        self._persist_artifact(artifact_id, envelope, content)
        return artifact_id

    def set_file_provenance(
        self, resource: str, content: str, source_artifact_ids: list[str]
    ) -> None:
        if any(item not in self.artifacts for item in source_artifact_ids):
            raise ValueError("UNKNOWN_FILE_PROVENANCE")
        binding = (sha(content), sorted(set(source_artifact_ids)))
        self.file_provenance[resource] = binding
        if self._db is not None:
            self._db.execute(
                "INSERT OR REPLACE INTO file_provenance VALUES (?, ?, ?, ?)",
                (self._workspace_identity, resource, binding[0], canonical_json(binding[1])),
            )
            self._db.commit()

    def file_parents(self, resource: str, content: str) -> list[str]:
        binding = self.file_provenance.get(resource)
        if binding is None or binding[0] != sha(content):
            return []
        return [item for item in binding[1] if item in self.artifacts]

    def create_derived_artifact(
        self,
        content: str,
        *,
        source_event_id: str,
        source_id: str,
        parents: list[str],
        transformation: str,
        origin_type: str = "MODEL_OUTPUT",
    ) -> str:
        """Conservatively inherit every exposed parent's security labels."""
        parent_ids = sorted(set(parents))
        if (
            source_event_id not in self._event_ids
            or not parent_ids
            or any(parent not in self.artifacts for parent in parent_ids)
            or transformation not in {"SUMMARY", "MODEL_REWRITE", "SERIALIZE"}
            or origin_type not in {"MODEL_OUTPUT", "CONTROL_PLANE"}
        ):
            raise ValueError("INVALID_DERIVATION")
        source_event = self._events_by_id[source_event_id]
        if (
            source_event["event_type"] != "CONTENT_SUMMARIZED"
            or not set(parent_ids).issubset(source_event["artifact_ids"])
            or self.payloads[source_event_id].get("transformation") != transformation
        ):
            raise ValueError("INVALID_DERIVATION")
        parent_bodies = [self.artifacts[parent].to_dict() for parent in parent_ids]
        confidentiality_order = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "SECRET")
        confidentiality = max(
            (body["confidentiality"] for body in parent_bodies),
            key=confidentiality_order.index,
        )
        permitted = set(parent_bodies[0]["allowed_uses"])
        forbidden: set[str] = set()
        for body in parent_bodies:
            permitted.intersection_update(body["allowed_uses"])
            forbidden.update(body["forbidden_uses"])
        permitted.difference_update(forbidden)
        artifact_id = new_id()
        envelope = ProvenanceEnvelope(
            {
                "schema_version": "1.0",
                "artifact_id": artifact_id,
                "content_ref": f"evidence://artifact/{artifact_id}",
                "content_hash": sha(content),
                "origin": {
                    "type": origin_type,
                    "source_id": source_id,
                    "event_id": source_event_id,
                },
                "authority": "DATA_ONLY",
                "integrity": "UNTRUSTED",
                "confidentiality": confidentiality,
                "allowed_uses": sorted(permitted),
                "forbidden_uses": sorted(forbidden),
                "parents": parent_ids,
                "transformations": [{"type": transformation, "version": "1", "mapping_ref": None}],
                "source_spans": [],
                "created_at": utc_text(utc_now()),
            }
        )
        self.artifacts[artifact_id] = envelope
        self.artifact_contents[artifact_id] = content
        self._persist_artifact(artifact_id, envelope, content)
        return artifact_id

    def public_ioc_content(self, source_artifact_id: str) -> str:
        source = self.artifacts.get(source_artifact_id)
        if source is None:
            raise ValueError("UNKNOWN_IOC_SOURCE")
        body = source.to_dict()
        if body["origin"]["type"] != "MCP_TOOL_RESULT" or body["confidentiality"] not in {
            "PUBLIC",
            "INTERNAL",
        }:
            raise ValueError("IOC_SOURCE_NOT_DECLASSIFIABLE")
        return render_public_ipv4_iocs(
            extract_public_ipv4_iocs(self.artifact_contents[source_artifact_id])
        )

    def create_sanitized_ioc_artifact(
        self, source_artifact_id: str, *, source_event_id: str
    ) -> str:
        """Whitelist transform: output is computed here, never accepted from a model."""
        if source_event_id not in self._event_ids:
            raise ValueError("UNKNOWN_PROVENANCE_PARENT")
        source_event = self._events_by_id[source_event_id]
        if (
            source_event["event_type"] != "CONTENT_SUMMARIZED"
            or source_artifact_id not in source_event["artifact_ids"]
            or self.payloads[source_event_id].get("transformation") != "IOC_EXTRACTION"
        ):
            raise ValueError("INVALID_IOC_DERIVATION")
        content = self.public_ioc_content(source_artifact_id)
        parent = self.artifacts[source_artifact_id].to_dict()
        forbidden = set(parent["forbidden_uses"])
        forbidden.discard("TRANSFER")
        allowed = set(parent["allowed_uses"])
        allowed.add("TRANSFER")
        allowed.difference_update(forbidden)
        artifact_id = new_id()
        envelope = ProvenanceEnvelope(
            {
                "schema_version": "1.0",
                "artifact_id": artifact_id,
                "content_ref": f"evidence://artifact/{artifact_id}",
                "content_hash": sha(content),
                "origin": {
                    "type": "SANITIZER_OUTPUT",
                    "source_id": "trusted-sanitizer:public-ipv4-v1",
                    "event_id": source_event_id,
                },
                "authority": "DATA_ONLY",
                "integrity": "UNTRUSTED",
                "confidentiality": "PUBLIC",
                "allowed_uses": sorted(allowed),
                "forbidden_uses": sorted(forbidden),
                "parents": [source_artifact_id],
                "transformations": [
                    {"type": "IOC_EXTRACTION", "version": "1", "mapping_ref": None}
                ],
                "source_spans": [],
                "created_at": utc_text(utc_now()),
            }
        )
        self.artifacts[artifact_id] = envelope
        self.artifact_contents[artifact_id] = content
        self._persist_artifact(artifact_id, envelope, content)
        return artifact_id

    def create_host_content(self, content: str, *, source_event_id: str) -> str:
        """Register bytes supplied by trusted Host code, never by model text."""
        event = self._events_by_id.get(source_event_id)
        if event is None or event["event_type"] != "CONTENT_REGISTERED":
            raise ValueError("INVALID_HOST_CONTENT_SOURCE")
        artifact_id = new_id()
        envelope = ProvenanceEnvelope(
            {
                "schema_version": "1.0",
                "artifact_id": artifact_id,
                "content_ref": f"evidence://artifact/{artifact_id}",
                "content_hash": sha(content),
                "origin": {
                    "type": "CONTROL_PLANE",
                    "source_id": "trusted-host:constant",
                    "event_id": source_event_id,
                },
                "authority": "DATA_ONLY",
                "integrity": "TRUSTED",
                "confidentiality": "PUBLIC",
                "allowed_uses": ["READ", "ANALYZE", "QUOTE", "WRITE_REPORT", "TRANSFER"],
                "forbidden_uses": ["AUTHORIZE", "EXECUTE", "CHANGE_POLICY", "DELEGATE"],
                "parents": [],
                "transformations": [],
                "source_spans": [],
                "created_at": utc_text(utc_now()),
            }
        )
        self.artifacts[artifact_id] = envelope
        self.artifact_contents[artifact_id] = content
        self._persist_artifact(artifact_id, envelope, content)
        return artifact_id

    def _persist_artifact(
        self, artifact_id: str, envelope: ProvenanceEnvelope, content: str
    ) -> None:
        if self._db is not None:
            self._db.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?)",
                (artifact_id, self.trace_id, canonical_json(envelope.to_dict()), content),
            )
            self._db.commit()

    def store_normalized_view(self, artifact_id: str, content: str) -> None:
        if artifact_id not in self.artifacts:
            raise ValueError("UNKNOWN_ARTIFACT")
        self.normalized_views[artifact_id] = content
        if self._db is not None:
            self._db.execute(
                "INSERT OR REPLACE INTO normalized_views VALUES (?, ?, ?)",
                (artifact_id, self.trace_id, content),
            )
            self._db.commit()

    def dag(self) -> dict[str, Any]:
        """No raw content or event payloads leave the trusted evidence store."""
        return load_json(
            canonical_json(
                {
                    "trace_id": self.trace_id,
                    "events": self.events,
                    "artifacts": [item.to_dict() for item in self.artifacts.values()],
                }
            )
        )

    def emit(
        self,
        event_type: str,
        *,
        actor_id: str,
        parents: list[str] | None = None,
        action_id: str | None = None,
        decision_id: str | None = None,
        artifact_ids: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        if any(parent not in self._event_ids for parent in (parents or [])) or any(
            artifact not in self.artifacts for artifact in (artifact_ids or [])
        ):
            raise ValueError("UNKNOWN_TRACE_PARENT")
        event_id = new_id()
        body = payload or {}
        event = {
            "schema_version": "1.0",
            "event_id": event_id,
            "trace_id": self.trace_id,
            "parent_event_ids": parents or [],
            "event_type": event_type,
            "actor_id": actor_id,
            "session_id": self._contract["session_id"],
            "contract_id": self._contract["contract_id"],
            "artifact_ids": artifact_ids or [],
            "action_id": action_id,
            "decision_id": decision_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sequence": len(self.events),
            "payload_ref": f"evidence://trace/{event_id}",
            "payload_hash": sha(body),
        }
        self.events.append(event)
        self._event_ids.add(event_id)
        self._events_by_id[event_id] = event
        self.payloads[event_id] = body
        if self._db is not None:
            self._db.execute(
                "INSERT INTO trace_events VALUES (?, ?, ?, ?)",
                (event_id, self.trace_id, canonical_json(event), canonical_json(body)),
            )
            self._db.commit()
        return event_id


class M1Gateway:
    @property
    def source_uses_enabled(self) -> bool:
        """Trusted runtime seam; production always enforces source use constraints."""
        return True

    @property
    def recovery_enabled(self) -> bool:
        return True

    def make_child_gateway(self, *args, **kwargs):
        return M1Gateway(*args, **kwargs)

    def __init__(
        self,
        proxy: StdioMCPProxy,
        contract: TaskContract,
        grant: TaskGrant,
        *,
        sensitive_resources: tuple[str, ...] = ("/workspace/case-001/secret.txt",),
        trace_db_path: Path | None = None,
        workspace_identity: str = "synthetic-workspace",
        shared_trace: TraceLedger | None = None,
        network_policy: NetworkPolicy | None = None,
        execution_policy: ExecutionPolicy | None = None,
        git_policy: GitPolicy | None = None,
        memory_policy: MemoryPolicy | None = None,
    ) -> None:
        if not sensitive_resources or any(
            local_scope(item) is None for item in sensitive_resources
        ):
            raise ValueError("INVALID_SENSITIVE_RESOURCE_SCOPE")
        self.proxy, self.contract, self.grant = proxy, contract, grant
        self.sensitive_resources = sensitive_resources
        self.network_policy = network_policy
        self.execution_policy = execution_policy
        self.git_policy = git_policy
        self.memory_policy = memory_policy
        if any(
            spec.server_version != (memory_policy.server_version if memory_policy else "0.1.0")
            for name, spec in proxy.registry.items()
            if name.startswith("memory.")
        ):
            raise ValueError("MEMORY_POLICY_BINDING_INVALID")
        if "network.fetch" in proxy.registry and (
            network_policy is None
            or proxy.registry["network.fetch"].server_version != network_policy.server_version
        ):
            raise ValueError("NETWORK_POLICY_BINDING_INVALID")
        if "execution.run" in proxy.registry and (
            execution_policy is None
            or proxy.registry["execution.run"].server_version != execution_policy.server_version
        ):
            raise ValueError("EXEC_POLICY_BINDING_INVALID")
        if any(name.startswith("git_delivery.") for name in proxy.registry) and (
            git_policy is None
            or any(
                spec.server_version != git_policy.server_version
                for name, spec in proxy.registry.items()
                if name.startswith("git_delivery.")
            )
        ):
            raise ValueError("GIT_POLICY_BINDING_INVALID")
        self.policy = M1Policy()
        trace_path = os.environ.get("SUJIE_TRACE_DB")
        self.trace = shared_trace or TraceLedger(
            contract,
            trace_db_path
            if trace_db_path is not None
            else Path(trace_path)
            if trace_path
            else None,
            workspace_identity=workspace_identity,
        )
        self._pending: dict[str, PendingApproval] = {}
        self._approval_lock = asyncio.Lock()
        self._budget_lock = asyncio.Lock()
        self._usage = {"tool_calls": 0, "network_calls": 0, "subagents": 0}
        self._exposed_artifacts: set[str] = set()
        self._last_exposure_event: str | None = None
        self._last_model_plan_event: str | None = None
        self._parent_gateway: M1Gateway | None = None
        self._child_grants: set[str] = set()
        if shared_trace is None:
            for spec in proxy.registry.values():
                self.trace.emit(
                    "TOOL_REGISTERED",
                    actor_id=spec.server_id,
                    payload={
                        "qualified_name": spec.qualified_name,
                        "version_hash": spec.version_hash,
                    },
                )

    async def spawn_child(
        self, child_grant: TaskGrant, *, analysis_inputs: tuple[str, ...] | None = None
    ) -> tuple[dict[str, Any], M1Gateway | None]:
        """Trusted Host only: reserve a narrowed child's entire budget up front."""
        parent, child = self.grant.to_dict(), child_grant.to_dict()
        valid_inputs = (
            isinstance(analysis_inputs, tuple)
            and 1 <= len(analysis_inputs) <= 8
            and all(isinstance(item, str) for item in analysis_inputs)
            and len(set(analysis_inputs)) == len(analysis_inputs)
            and set(analysis_inputs) <= self._exposed_artifacts
        )
        inputs = sorted(analysis_inputs) if valid_inputs else sorted(self._exposed_artifacts)
        proposed = self.trace.emit(
            "TOOL_PROPOSED",
            actor_id=parent["subject_id"],
            parents=self._proposal_parents(),
            artifact_ids=inputs,
            payload={
                "tool": "host.delegate",
                "child_grant_hash": sha(child),
                "arguments_hash": sha({"child_grant_hash": sha(child), "input_artifacts": inputs}),
                "model_plan_event_id": self._last_model_plan_event,
                "analysis_only": analysis_inputs is not None,
            },
        )

        def reject(code: str) -> tuple[dict[str, Any], None]:
            self.trace.emit(
                "TOOL_CALL_DECIDED",
                actor_id=parent["subject_id"],
                parents=[proposed],
                payload={"decision": "BLOCK", "reason": code},
            )
            return {"ok": False, "decision": "BLOCK", "code": code}, None

        if child["contract_id"] != self.contract.to_dict()["contract_id"]:
            return reject("GRANT_MISMATCH")
        if child["subject_id"] == parent["subject_id"] or child["grant_id"] in self._child_grants:
            return reject("CHILD_IDENTITY_INVALID")
        if analysis_inputs is not None:
            if not valid_inputs:
                return reject("ANALYSIS_INPUT_INVALID")
            if not set(child["effects"]) <= {"file.read", "agent.delegate"}:
                return reject("ANALYSIS_CHILD_EFFECT_FORBIDDEN")
            for item in inputs:
                source = self.trace.artifacts[item].to_dict()
                if source["confidentiality"] not in {"PUBLIC", "INTERNAL"}:
                    return reject("DELEGATION_SENSITIVE_INPUT")
                if self.source_uses_enabled and (
                    "ANALYZE" not in source["allowed_uses"] or "ANALYZE" in source["forbidden_uses"]
                ):
                    return reject("PROVENANCE_FORBIDS_ANALYSIS")
        if set(parent["budgets"]) != {"tool_calls", "network_calls", "subagents"} or set(
            child["budgets"]
        ) != {"tool_calls", "network_calls", "subagents"}:
            return reject("DELEGATION_BUDGETS_INCOMPLETE")
        try:
            assert_child_within_parent(self.grant, child_grant, now=utc_now())
        except InvariantViolation as error:
            return reject(str(error))
        spec = ToolSpec(
            "host.delegate",
            self.contract.to_dict()["principal_id"],
            "trusted-host",
            "delegate",
            sha(
                "trusted-host-analysis-delegate-v1"
                if analysis_inputs is not None
                else "trusted-host-delegate-v1"
            ),
            {},
        )
        action = semantic_action(
            "host.delegate",
            {
                "child_grant_hash": sha(child),
                "analysis_only": analysis_inputs is not None,
                "analysis_resources": child["resource_scopes"],
            },
            spec,
            self.contract,
            self.grant,
            input_artifacts=inputs,
        )
        decision = self.policy.decide(action, self.contract, self.grant)
        if decision.decision != "ALLOW":
            return reject(decision.reason)
        required = {
            "tool_calls": child["budgets"]["tool_calls"] + 1,
            "network_calls": child["budgets"]["network_calls"],
            "subagents": child["budgets"]["subagents"] + 1,
        }
        async with self._budget_lock:
            if any(
                self._usage[key] + amount
                > min(self.contract.to_dict()["budgets"][key], parent["budgets"][key])
                for key, amount in required.items()
            ):
                return reject("DELEGATION_BUDGET_EXHAUSTED")
            if (
                self.source_uses_enabled
                and analysis_inputs is None
                and any(
                    "DELEGATE" in self.trace.artifacts[item].to_dict()["forbidden_uses"]
                    for item in inputs
                )
            ):
                return reject("PROVENANCE_FORBIDS_DELEGATE")
            for key, amount in required.items():
                self._usage[key] += amount
            self._child_grants.add(child["grant_id"])
        decided = self.trace.emit(
            "TOOL_CALL_DECIDED",
            actor_id=parent["subject_id"],
            parents=[proposed],
            action_id=action.to_dict()["action_id"],
            payload={
                "decision": "ALLOW",
                "reason": decision.reason,
                "semantic_action": action.to_dict(),
            },
        )
        executed = self.trace.emit(
            "EXECUTION_RESULT",
            actor_id=parent["subject_id"],
            parents=[decided],
            action_id=action.to_dict()["action_id"],
            payload={"tool": "host.delegate", "ok": True, "child_grant_id": child["grant_id"]},
        )
        child_gateway = self.make_child_gateway(
            self.proxy,
            self.contract,
            child_grant,
            sensitive_resources=self.sensitive_resources,
            shared_trace=self.trace,
            network_policy=self.network_policy,
            execution_policy=self.execution_policy,
            git_policy=self.git_policy,
            memory_policy=self.memory_policy,
        )
        child_gateway._parent_gateway = self
        child_gateway._exposed_artifacts = set(inputs)
        child_gateway._last_exposure_event = executed
        return {"ok": True, "decision": "ALLOW", "child_grant_id": child["grant_id"]}, child_gateway

    def adopt_child_artifact(self, child_gateway: M1Gateway, artifact_id: str) -> None:
        """Expose a verified child Artifact to the parent without changing its lineage."""
        if (
            child_gateway._parent_gateway is not self
            or child_gateway.trace is not self.trace
            or artifact_id not in child_gateway._exposed_artifacts
        ):
            raise ValueError("INVALID_CHILD_ARTIFACT")
        event_id = self.trace.emit(
            "MODEL_EXPOSED",
            actor_id=self.grant.to_dict()["subject_id"],
            parents=[child_gateway._last_exposure_event]
            if child_gateway._last_exposure_event
            else [],
            artifact_ids=[artifact_id],
            payload={
                "tool": "host.delegate",
                "child_grant_id": child_gateway.grant.to_dict()["grant_id"],
            },
        )
        self._exposed_artifacts.add(artifact_id)
        self._last_exposure_event = event_id

    def register_user_input(self, text: str) -> str:
        """Authenticated Host input; request authority never changes Contract or Grant."""
        if not isinstance(text, str) or not 1 <= len(text) <= 4096:
            raise ValueError("INVALID_USER_INPUT")
        try:
            text.encode("utf-8")
        except UnicodeError:
            raise ValueError("INVALID_USER_INPUT") from None
        actor = self.contract.to_dict()["principal_id"]
        event = self.trace.emit(
            "USER_MESSAGE",
            actor_id=actor,
            payload={"content_hash": sha(text), "kind": "SCOPED_USER_SUPPLEMENT"},
        )
        # Credential-shaped supplemental input is held locally, not sent to cloud.
        confidentiality = "SECRET" if re.search(r"\bsk-[A-Za-z0-9_-]{20,}", text) else "INTERNAL"
        artifact = self.trace.create_artifact(
            text,
            source_event_id=event,
            source_id="authenticated-user:supplement",
            origin_type="USER_MESSAGE",
            authority="USER_REQUEST",
            confidentiality=confidentiality,
        )
        view, finding = detect_indirect(text, artifact, new_id(), attack_source="DIRECT")
        self.trace.store_normalized_view(artifact, view)
        parent = self.trace.emit(
            "CONTENT_NORMALIZED",
            actor_id=actor,
            parents=[event],
            artifact_ids=[artifact],
            payload={"detector_version": DETECTOR_VERSION},
        )
        if finding is not None:
            parent = self.trace.emit(
                "DETECTION_FINDING",
                actor_id=actor,
                parents=[parent],
                artifact_ids=[artifact],
                payload={"finding": finding.to_dict()},
            )
        self._last_exposure_event = self.trace.emit(
            "CONTEXT_REGISTERED",
            actor_id=actor,
            parents=[parent],
            artifact_ids=[artifact],
            payload={"kind": "USER_SUPPLEMENT"},
        )
        self._exposed_artifacts.add(artifact)
        return artifact

    def record_visible_plan(
        self, calls: list[dict], content_hash: str, *, response_event_id: str | None = None
    ) -> None:
        """Record all visible proposals, including the first unexposed model round."""
        if (
            len(calls) > 4
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", content_hash)
            or any(
                set(call) != {"tool", "raw_arguments_hash"}
                or call["tool"]
                not in {*self.proxy.registry, "host.delegate", "host.analyze_evidence", "unknown"}
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", call["raw_arguments_hash"])
                for call in calls
            )
        ):
            raise ValueError("INVALID_VISIBLE_PLAN")
        if response_event_id is not None and (
            response_event_id not in self.trace._event_ids
            or self.trace._events_by_id[response_event_id]["event_type"] != "MODEL_RESPONSE_CHECKED"
        ):
            raise ValueError("INVALID_MODEL_RESPONSE_PARENT")
        self._last_model_plan_event = self.trace.emit(
            "CONTENT_REGISTERED",
            actor_id=self.grant.to_dict()["subject_id"],
            parents=[response_event_id]
            if response_event_id
            else ([self._last_exposure_event] if self._last_exposure_event else []),
            payload={
                "kind": "MODEL_VISIBLE_PLAN",
                "visible_plan": calls,
                "plan_text_hash": content_hash,
            },
        )

    def _proposal_parents(self) -> list[str]:
        return list(
            dict.fromkeys(
                event
                for event in (self._last_exposure_event, self._last_model_plan_event)
                if event is not None
            )
        )

    def reference_artifact_ids(self) -> list[str]:
        """Avoid advertising two representations of the same selected document.

        Both remain exposed for policy and request provenance. If a top-level
        content artifact exists, quote/delegation menus retain that document ID;
        a nested-only result instead advertises its complete structured source.
        This does not remove a source from enforcement or enlarge a child grant.
        """
        references = []
        for identifier in sorted(self._exposed_artifacts):
            body = self.trace.artifacts[identifier].to_dict()
            duplicate = body["origin"]["source_id"].endswith(":structured-result") and any(
                self.trace.artifacts[parent].to_dict()["origin"]["event_id"]
                == body["origin"]["event_id"]
                for parent in body["parents"]
            )
            if not duplicate:
                references.append(identifier)
        return references

    def record_model_output(
        self,
        content: str,
        *,
        transformation: str = "SUMMARY",
        input_artifacts: tuple[str, ...] | None = None,
        response_event_id: str | None = None,
    ) -> str:
        """Trusted Host hook: register free-form output before it is used in a tool call."""
        if (
            not isinstance(content, str)
            or not self._exposed_artifacts
            or transformation not in {"SUMMARY", "MODEL_REWRITE", "SERIALIZE"}
        ):
            raise ValueError("INVALID_MODEL_OUTPUT")
        parents = sorted(
            self._exposed_artifacts if input_artifacts is None else set(input_artifacts)
        )
        if not set(parents) <= self._exposed_artifacts:
            raise ValueError("INVALID_MODEL_OUTPUT_SOURCE")
        if response_event_id is not None and (
            response_event_id not in self.trace._event_ids
            or self.trace._events_by_id[response_event_id]["event_type"] != "MODEL_RESPONSE_CHECKED"
        ):
            raise ValueError("INVALID_MODEL_RESPONSE_PARENT")
        event_id = self.trace.emit(
            "CONTENT_SUMMARIZED",
            actor_id=self.grant.to_dict()["subject_id"],
            parents=[response_event_id]
            if response_event_id
            else ([self._last_exposure_event] if self._last_exposure_event else []),
            artifact_ids=parents,
            payload={"transformation": transformation, "content_hash": sha(content)},
        )
        artifact_id = (
            self.trace.create_derived_artifact(
                content,
                source_event_id=event_id,
                source_id="trusted-host:model-output",
                parents=parents,
                transformation=transformation,
            )
            if parents
            else self.trace.create_artifact(
                content,
                source_event_id=event_id,
                source_id="trusted-host:model-output",
                origin_type="MODEL_OUTPUT",
            )
        )
        self._exposed_artifacts.add(artifact_id)
        self._last_exposure_event = event_id
        return artifact_id

    def record_semantic_finding(
        self, content: str, reason_code: str, *, detector_version: str
    ) -> str:
        """Trusted Host hook; a model finding records risk but never grants authority."""
        families = {
            "OVERRIDE": "CONTEXT_HIJACK",
            "ROLE_SPOOF": "ROLE_SPOOFING",
            "EXFILTRATION": "DATA_EXFILTRATION",
            "ENCODED_INSTRUCTION": "CHARACTER_ENCODING",
        }
        if reason_code not in families or not detector_version.startswith("semantic-"):
            raise ValueError("INVALID_SEMANTIC_FINDING")
        matches = [
            artifact_id
            for artifact_id in self._exposed_artifacts
            if self.trace.artifact_contents.get(artifact_id) == content
            and self.trace.artifacts[artifact_id]
            .to_dict()["origin"]["source_id"]
            .startswith("evidence.read_alert:")
        ]
        if not matches:
            raise ValueError("UNEXPOSED_SEMANTIC_SOURCE")
        artifact_id = max(matches)
        finding = DetectionFinding(
            {
                "schema_version": "1.0",
                "finding_id": new_id(),
                "attack_source": "INDIRECT",
                "attack_family": families[reason_code],
                "spans": [{"artifact_id": artifact_id, "start": 0, "end": len(content)}],
                "normalized_view": f"evidence://view/{artifact_id}/nfkc-v1",
                "confidence": 0.5,
                "reasons": [f"semantic_{reason_code.lower()}", "uncalibrated_binary_result"],
                "detector_version": detector_version[:64],
            }
        )
        event_id = self.trace.emit(
            "DETECTION_FINDING",
            actor_id=self.grant.to_dict()["subject_id"],
            parents=[self._last_exposure_event] if self._last_exposure_event else [],
            artifact_ids=[artifact_id],
            payload={"finding": finding.to_dict()},
        )
        self._last_exposure_event = event_id
        return event_id

    def sanitize_public_iocs(self, source_artifact_id: str) -> tuple[str, str]:
        """Trusted Host hook for one reviewed, deterministic declassification."""
        if source_artifact_id not in self._exposed_artifacts:
            raise ValueError("IOC_SOURCE_NOT_EXPOSED")
        content = self.trace.public_ioc_content(source_artifact_id)
        event_id = self.trace.emit(
            "CONTENT_SUMMARIZED",
            actor_id=self.grant.to_dict()["subject_id"],
            parents=[self._last_exposure_event] if self._last_exposure_event else [],
            artifact_ids=[source_artifact_id],
            payload={"transformation": "IOC_EXTRACTION", "content_hash": sha(content)},
        )
        artifact_id = self.trace.create_sanitized_ioc_artifact(
            source_artifact_id, source_event_id=event_id
        )
        self._exposed_artifacts.add(artifact_id)
        self._last_exposure_event = event_id
        return artifact_id, content

    def register_host_content(self, content: str) -> str:
        """Trusted Host only: attest exact independent content for later egress."""
        if not isinstance(content, str) or not content:
            raise ValueError("INVALID_HOST_CONTENT")
        event_id = self.trace.emit(
            "CONTENT_REGISTERED",
            actor_id=self.contract.to_dict()["principal_id"],
            parents=[self._last_exposure_event] if self._last_exposure_event else [],
            payload={"content_hash": sha(content)},
        )
        artifact_id = self.trace.create_host_content(content, source_event_id=event_id)
        self._exposed_artifacts.add(artifact_id)
        self._last_exposure_event = event_id
        return artifact_id

    async def record_host_block(self, tool: str, args: dict[str, Any], code: str) -> dict:
        """A trusted Host can only tighten a decision, with a recorded proposal."""
        if code not in {
            "DECLINED_ACTION_REPEATED",
            "ALERT_ID_MISMATCH",
            "WEB_URL_MISMATCH",
            "UNKNOWN_MODEL_TOOL",
            "INVALID_DELEGATION",
            "DELEGATION_ALREADY_USED",
            "DELEGATION_SENSITIVE_INPUT",
            "DELEGATION_INPUT_LIMIT",
            "ANALYSIS_INPUT_INVALID",
            "ANALYSIS_ALREADY_USED",
            "ANALYSIS_INPUT_LIMIT",
            "ANALYSIS_NOT_AUTHORIZED",
            "ANALYSIS_SENSITIVE_OR_CHANGED_INPUT",
            "PROVENANCE_FORBIDS_ANALYSIS",
        }:
            raise ValueError("INVALID_HOST_BLOCK")
        actor = self.grant.to_dict()["subject_id"]
        proposed = self.trace.emit(
            "TOOL_PROPOSED",
            actor_id=actor,
            parents=self._proposal_parents(),
            artifact_ids=sorted(self._exposed_artifacts),
            payload={"tool": tool, "arguments_hash": sha(args), "kind": "HOST_REFUSAL"},
        )
        await self._reserve_budget("tool_calls")
        self.trace.emit(
            "TOOL_CALL_DECIDED",
            actor_id=actor,
            parents=[proposed],
            payload={"tool": tool, "decision": "BLOCK", "reason": code},
        )
        return {"ok": False, "decision": "BLOCK", "code": code}

    async def call(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        _trusted_probe: bool = False,
        _probe_parent: str | None = None,
    ) -> dict[str, Any]:
        actor = (
            self.contract.to_dict()["principal_id"]
            if _trusted_probe
            else self.grant.to_dict()["subject_id"]
        )
        exposed = sorted(self._exposed_artifacts)
        proposed = self.trace.emit(
            "TOOL_PROPOSED",
            actor_id=actor,
            parents=[_probe_parent]
            if _trusted_probe and _probe_parent
            else []
            if _trusted_probe
            else self._proposal_parents(),
            artifact_ids=exposed,
            payload={
                "tool": tool,
                "arguments_hash": sha(args),
                **({"kind": "TRUSTED_HOST_STATE_CHECK"} if _trusted_probe else {}),
            },
        )
        if not await self._reserve_budget("tool_calls"):
            self.trace.emit(
                "TOOL_CALL_DECIDED",
                actor_id=actor,
                parents=[proposed],
                payload={"decision": "BLOCK", "reason": "TOOL_BUDGET_EXHAUSTED"},
            )
            return {"ok": False, "decision": "BLOCK", "code": "TOOL_BUDGET_EXHAUSTED"}
        try:
            action = semantic_action(
                tool,
                args,
                self.proxy.registry[tool],
                self.contract,
                self.grant,
                input_artifacts=exposed,
                sensitive_resources=self.sensitive_resources,
                network_policy=self.network_policy,
                execution_policy=self.execution_policy,
                git_policy=self.git_policy,
                memory_policy=self.memory_policy,
            )
        except (KeyError, TypeError, ValueError):
            self.trace.emit(
                "TOOL_CALL_DECIDED",
                actor_id=actor,
                parents=[proposed],
                payload={"decision": "BLOCK", "reason": "INVALID_ACTION"},
            )
            return {"ok": False, "decision": "BLOCK", "code": "INVALID_ACTION"}
        decision = self.policy.decide(action, self.contract, self.grant)
        if (
            self.memory_policy is not None
            and self.source_uses_enabled
            and tool == "memory.write"
            and decision.decision in {"ALLOW", "ASK"}
            and action.to_dict()["effect"]["operation"] == "MEMORY_WRITE_PINNED"
            and not any(
                self.trace.artifact_contents[item] == args["content"]
                and "STORE_EVIDENCE" in self.trace.artifacts[item].to_dict()["allowed_uses"]
                and "STORE_EVIDENCE" not in self.trace.artifacts[item].to_dict()["forbidden_uses"]
                and self.trace.artifacts[item].to_dict()["confidentiality"]
                in {"PUBLIC", "INTERNAL"}
                for item in exposed
            )
        ):
            decision = GateDecision("BLOCK", True, "MEMORY_SOURCE_UNREGISTERED", action)
        if (
            tool == "git_delivery.push"
            and decision.decision in {"ALLOW", "ASK"}
            and not await self._git_state_matches(proposed)
        ):
            decision = GateDecision("BLOCK", True, "GIT_STATE_CHANGED", action)
        copied_artifact_id = None
        if self.source_uses_enabled and decision.decision in {"ALLOW", "ASK"}:
            copied_artifact_id = (
                self._copied_network_artifact(action, args)
                if tool == "network.fetch"
                else self._copied_forbidden_artifact(action, args)
            )
        if copied_artifact_id is not None:
            decision = GateDecision("BLOCK", True, "PROVENANCE_FORBIDS_TRANSFER", action)
        elif (
            decision.decision in {"ALLOW", "ASK"}
            and self.source_uses_enabled
            and action.to_dict()["effect"]["kind"] == "data.transfer"
            and exposed
            and not (
                self._has_registered_network_payload(args)
                if tool == "network.fetch"
                else self._has_registered_transfer_content(args)
            )
        ):
            decision = GateDecision("BLOCK", True, "EGRESS_SOURCE_UNREGISTERED", action)
        if decision.decision in {"ALLOW", "ASK"} and (
            action.to_dict()["effect"]["kind"] == "data.transfer" or tool == "network.fetch"
        ):
            if not await self._reserve_budget("network_calls"):
                decision = GateDecision("BLOCK", True, "NETWORK_BUDGET_EXHAUSTED", action)
        decision_id = new_id()
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
                "matched_facts": [
                    {"field": "action.effect.kind", "summary": action.to_dict()["effect"]["kind"]},
                    {
                        "field": "contract.allowed_purposes",
                        "summary": ",".join(self.contract.to_dict()["allowed_purposes"]),
                    },
                ]
                + (
                    [{"field": "provenance.copied_artifact_id", "summary": copied_artifact_id}]
                    if copied_artifact_id is not None
                    else []
                ),
                "policy_snapshot_hash": self.contract.to_dict()["policy_snapshot_hash"],
                "contract_id": self.contract.to_dict()["contract_id"],
                "grant_id": self.grant.to_dict()["grant_id"],
                "timestamp": utc_text(utc_now()),
            }
        )
        alignment = (
            explain_alignment(
                decision.reason,
                action.to_dict(),
                self.contract.to_dict(),
                self.grant.to_dict(),
                required_purpose=self.policy.EFFECT_PURPOSE.get(action.to_dict()["effect"]["kind"]),
                copied_artifact_id=copied_artifact_id,
            )
            if decision.decision == "BLOCK"
            else None
        )
        decided = self.trace.emit(
            "TOOL_CALL_DECIDED",
            actor_id=actor,
            parents=[proposed],
            action_id=action.to_dict()["action_id"],
            decision_id=decision_id,
            artifact_ids=exposed,
            payload={
                "decision": decision.decision,
                "reason": decision.reason,
                "record": decision_record.to_dict(),
                "alignment": alignment,
                "semantic_action": {
                    "effect": action.to_dict()["effect"],
                    "input_artifacts": action.to_dict()["input_artifacts"],
                },
            },
        )
        if decision.decision == "ASK":
            now = utc_now()
            requested = self.trace.emit(
                "APPROVAL_REQUESTED",
                actor_id=actor,
                parents=[decided],
                action_id=action.to_dict()["action_id"],
                decision_id=decision_id,
                payload={"expires_in_seconds": 300},
            )
            async with self._approval_lock:
                self._pending[decision_id] = PendingApproval(
                    decision=decision_record,
                    action=action,
                    tool=tool,
                    arguments_json=canonical_json(args),
                    input_content_hash=self._input_content_hash(args),
                    provenance_snapshot_hash=self._provenance_hash(exposed),
                    requested_event_id=requested,
                    created_at=now,
                    expires_at=now + timedelta(minutes=5),
                    review_metadata=self.git_policy.review(args)
                    if tool == "git_delivery.push"
                    else None,
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
            result = await self.proxy.invoke(tool, args)
            result_snapshot = snapshot_tool_result(result)
            result = result_snapshot.payload()
        except RuntimeError as error:
            self.trace.emit(
                "EXECUTION_RESULT",
                actor_id=actor,
                parents=[decided],
                action_id=action.to_dict()["action_id"],
                decision_id=decision_id,
                payload={"tool": tool, "ok": False, "code": str(error)},
            )
            return {
                "ok": False,
                "decision": "ALLOW",
                "code": str(error)
                if isinstance(error, ToolResultError)
                else "TOOL_EXECUTION_FAILED",
            }
        executed = self.trace.emit(
            "EXECUTION_RESULT",
            actor_id=actor,
            parents=[decided],
            action_id=action.to_dict()["action_id"],
            decision_id=decision_id,
            payload={"tool": tool, "ok": True},
        )
        self._track_file_write(tool, args, action, executed)
        try:
            self._record_tool_result(
                tool, result, action, executed, expose=True, snapshot=result_snapshot
            )
        except ResultScanRejected as rejected:
            # The tool already executed; only its unscanned result is withheld.
            return {"ok": False, "decision": "ALLOW", "code": rejected.code}
        return {"ok": True, "decision": "ALLOW", "data": result}

    @staticmethod
    def _input_content_hash(arguments: dict[str, Any]) -> str:
        return sha(arguments.get("content", arguments))

    async def _git_state_matches(self, parent: str) -> bool:
        if self.git_policy is None:
            return False
        result = await self.call(
            "git_delivery.state", {}, _trusted_probe=True, _probe_parent=parent
        )
        state = result.get("data", {})
        matches = (
            result.get("ok", False)
            and state.get("valid") is True
            and state.get("state_hash") == self.git_policy.state_hash
        )
        metadata = {
            "valid": state.get("valid") is True,
            "expected_state_hash": self.git_policy.state_hash,
        }
        for name in ("state_hash", "commit", "expected_old"):
            value = state.get(name)
            if isinstance(value, str) and (value == "" or re.fullmatch(r"[0-9a-f]{40,64}", value)):
                metadata[name] = value
        self.trace.emit(
            "CONTENT_REGISTERED",
            actor_id=self.contract.to_dict()["principal_id"],
            parents=[self.trace.events[-1]["event_id"]],
            payload={
                "kind": "GIT_STATE_OBSERVED",
                "status": "MATCH" if matches else "UNVERIFIED",
                "git_state": metadata,
            },
        )
        return matches

    def _provenance_hash(self, artifact_ids: list[str]) -> str:
        return sha([self.trace.artifacts[item].to_dict() for item in artifact_ids])

    def _copied_forbidden_artifact(
        self, action: SemanticAction, arguments: dict[str, Any]
    ) -> str | None:
        """Block direct copies of exposed non-transferable content at the tool boundary.

        This is deliberately limited to verbatim content of meaningful length. Mere
        exposure does not taint unrelated output, and transformed excerpts need a
        separate detector or human review rather than a claim of exact lineage.
        """
        data = action.to_dict()
        if data["effect"]["kind"] != "data.transfer":
            return None
        payload = arguments.get("content")
        if not isinstance(payload, str):
            return None
        for artifact_id in data["input_artifacts"]:
            envelope = self.trace.artifacts[artifact_id].to_dict()
            source = self.trace.artifact_contents[artifact_id]
            if "TRANSFER" in envelope["forbidden_uses"] and len(source) >= 16 and source in payload:
                return artifact_id
        return None

    def _has_registered_transfer_content(self, arguments: dict[str, Any]) -> bool:
        payload = arguments.get("content")
        return isinstance(payload, str) and any(
            self.trace.artifact_contents[artifact_id] == payload
            and "TRANSFER" in self.trace.artifacts[artifact_id].to_dict()["allowed_uses"]
            and "TRANSFER" not in self.trace.artifacts[artifact_id].to_dict()["forbidden_uses"]
            for artifact_id in self._exposed_artifacts
        )

    def _copied_network_artifact(self, action: SemanticAction, arguments: dict) -> str | None:
        for identifier in action.to_dict()["input_artifacts"]:
            envelope = self.trace.artifacts[identifier].to_dict()
            text = self.trace.artifact_contents[identifier]
            if text and (
                envelope["confidentiality"] == "SECRET"
                or (len(text) >= 16 and "TRANSFER" in envelope["forbidden_uses"])
            ):
                if contains_protected(arguments, (text,)):
                    return identifier
        return None

    def _has_registered_network_payload(self, arguments: dict) -> bool:
        values = payload_values(
            arguments["url"], arguments.get("headers", {}), arguments.get("body", "")
        )
        return all(
            any(
                self.trace.artifact_contents[identifier] == value
                and "TRANSFER" in self.trace.artifacts[identifier].to_dict()["allowed_uses"]
                and "TRANSFER" not in self.trace.artifacts[identifier].to_dict()["forbidden_uses"]
                and self.trace.artifacts[identifier].to_dict()["confidentiality"]
                in {"PUBLIC", "INTERNAL"}
                for identifier in self._exposed_artifacts
            )
            for value in values
        )

    def _track_file_write(
        self,
        tool: str,
        arguments: dict[str, Any],
        action: SemanticAction,
        executed_event: str,
    ) -> None:
        if tool not in {"operations.write_file", "memory.write"}:
            return
        content = arguments["content"]
        resource = action.to_dict()["effect"]["resources"][0]
        parents = action.to_dict()["input_artifacts"]
        exact = [
            artifact_id
            for artifact_id in parents
            if self.trace.artifact_contents[artifact_id] == content
        ]
        parents = exact or parents
        if parents:
            derived_event = self.trace.emit(
                "CONTENT_SUMMARIZED",
                actor_id=self.grant.to_dict()["subject_id"],
                parents=[executed_event],
                action_id=action.to_dict()["action_id"],
                artifact_ids=parents,
                payload={"transformation": "SERIALIZE", "content_hash": sha(content)},
            )
            written_artifact = self.trace.create_derived_artifact(
                content,
                source_event_id=derived_event,
                source_id=f"trusted-gateway:file-write:{resource}"[:512],
                parents=parents,
                transformation="SERIALIZE",
            )
            self.trace.set_file_provenance(resource, content, [written_artifact])
        else:
            self.trace.set_file_provenance(resource, content, [])

    def _record_tool_result(
        self,
        tool: str,
        data: dict[str, Any],
        action: SemanticAction,
        executed_event: str,
        *,
        expose: bool,
        snapshot: ToolResultSnapshot | None = None,
    ) -> tuple[str, ...]:
        """Register and scan a result; raise ResultScanRejected if any text is unscannable."""
        snapshot = snapshot or snapshot_tool_result(data)
        documents = self._record_document_results(
            tool, snapshot, action, executed_event, expose=expose
        )
        effect = action.to_dict()["effect"]
        actor = self.grant.to_dict()["subject_id"]
        if tool in {"memory.read", "memory.write"} and self.memory_policy is not None:
            self.trace.emit(
                "MEMORY_READ" if tool == "memory.read" else "MEMORY_WRITTEN",
                actor_id=actor,
                parents=[executed_event],
                action_id=action.to_dict()["action_id"],
                payload={
                    "key": data.get("key"),
                    "revision": data.get("revision"),
                    "content_sha256": data.get("content_sha256"),
                },
            )
        content_artifact = None
        content = data.get("content")
        if isinstance(content, str):
            source_id = (
                f"{tool}:{data.get('resource', data.get('alert_id', data.get('key', 'result')))}"[
                    :512
                ]
            )
            parents = (
                self.trace.file_parents(effect["resources"][0], content)
                if tool in {"operations.read_file", "memory.read"}
                else action.to_dict()["input_artifacts"]
                if tool == "execution.run"
                else []
            )
            artifact_id = self.trace.create_artifact(
                content,
                source_event_id=executed_event,
                source_id=source_id,
                confidentiality="SECRET" if effect["kind"] == "credential.read" else "INTERNAL",
                parents=parents,
                origin_type="MEMORY"
                if tool == "memory.read"
                else "WEB_PAGE"
                if tool == "network.fetch"
                else "MCP_TOOL_RESULT",
            )
            content_artifact = artifact_id
            read = self.trace.emit(
                "RESOURCE_READ",
                actor_id=actor,
                parents=[executed_event],
                action_id=action.to_dict()["action_id"],
                artifact_ids=[artifact_id],
                payload={"tool": tool, "content_hash": sha(content)},
            )
            try:
                view, finding = detect_indirect(
                    content,
                    artifact_id,
                    new_id(),
                    attack_source="MEMORY" if tool == "memory.read" else "INDIRECT",
                )
            except ScanLimitExceeded:
                code = "CONTENT_SCAN_LIMIT_EXCEEDED"
                self.trace.emit(
                    "CONTENT_REGISTERED",
                    actor_id=actor,
                    parents=[read],
                    action_id=action.to_dict()["action_id"],
                    artifact_ids=[artifact_id],
                    payload={
                        "tool": tool,
                        "scan_status": "REJECTED",
                        "code": code,
                        "detector_version": DETECTOR_VERSION,
                    },
                )
                # Result rejection cannot erase the audit of an effect that ran.
                if effect["side_effect"]:
                    self.trace.emit(
                        "RESOURCE_AFFECTED",
                        actor_id=actor,
                        parents=[executed_event],
                        action_id=action.to_dict()["action_id"],
                        artifact_ids=action.to_dict()["input_artifacts"],
                        payload={"kind": effect["kind"], "resources": effect["resources"]},
                    )
                raise ResultScanRejected(code)
            if tool == "memory.read" and finding is None:
                finding = deferred_memory_finding(content, view, artifact_id, new_id())
            self.trace.store_normalized_view(artifact_id, view)
            normalized = self.trace.emit(
                "CONTENT_NORMALIZED",
                actor_id=actor,
                parents=[read],
                action_id=action.to_dict()["action_id"],
                artifact_ids=[artifact_id],
                payload={
                    "view_ref": f"evidence://view/{artifact_id}/nfkc-v1",
                    "view_hash": sha(view),
                    "detector_version": finding.to_dict()["detector_version"]
                    if finding
                    else DETECTOR_VERSION,
                },
            )
            exposure_parent = normalized
            if finding is not None:
                exposure_parent = self.trace.emit(
                    "DETECTION_FINDING",
                    actor_id=actor,
                    parents=[normalized],
                    action_id=action.to_dict()["action_id"],
                    artifact_ids=[artifact_id],
                    payload={"finding": finding.to_dict()},
                )
            if expose:
                self._last_exposure_event = self.trace.emit(
                    "MODEL_EXPOSED",
                    actor_id=actor,
                    parents=[exposure_parent],
                    action_id=action.to_dict()["action_id"],
                    artifact_ids=[artifact_id],
                    payload={"tool": tool},
                )
                self._exposed_artifacts.add(artifact_id)
        structured = self._record_structured_result(
            tool, snapshot, action, executed_event, content_artifact, expose=expose
        )
        if effect["side_effect"]:
            self.trace.emit(
                "RESOURCE_AFFECTED",
                actor_id=actor,
                parents=[executed_event],
                action_id=action.to_dict()["action_id"],
                artifact_ids=action.to_dict()["input_artifacts"],
                payload={"kind": effect["kind"], "resources": effect["resources"]},
            )
        ordinary = (content_artifact, structured) if content_artifact else (structured,)
        return (*ordinary, *documents)

    def _record_document_results(
        self,
        tool: str,
        snapshot: ToolResultSnapshot,
        action: SemanticAction,
        executed_event: str,
        *,
        expose: bool,
    ) -> tuple[str, ...]:
        """Record extracted sources before returning inline document results to the model."""
        actor = self.grant.to_dict()["subject_id"]
        artifacts = []
        for path, document in tool_documents(snapshot.payload()):
            if document.status != "ok":
                self.trace.emit(
                    "CONTENT_REGISTERED",
                    actor_id=actor,
                    parents=[executed_event],
                    action_id=action.to_dict()["action_id"],
                    payload={
                        "tool": tool,
                        "kind": "DOCUMENT",
                        "scan_status": "REJECTED",
                        "code": document.code,
                    },
                )
                raise ResultScanRejected(document.code)
            ids = []
            for index, segment in enumerate(document.segments):
                artifact = self.trace.create_artifact(
                    segment.text,
                    source_event_id=executed_event,
                    source_id=f"{tool}:document:{len(artifacts)}:{index}",
                    confidentiality="SECRET"
                    if action.to_dict()["effect"]["kind"] == "credential.read"
                    else "INTERNAL",
                    parents=action.to_dict()["input_artifacts"] if tool == "execution.run" else [],
                )
                ids.append(artifact)
                self.trace.store_normalized_view(artifact, document_normalized_view(segment.text))
                self.trace.emit(
                    "CONTENT_REGISTERED",
                    actor_id=actor,
                    parents=[executed_event],
                    action_id=action.to_dict()["action_id"],
                    artifact_ids=[artifact],
                    payload={
                        "tool": tool,
                        "kind": "DOCUMENT",
                        "document_source": segment.labels,
                        "result_path": safe_path(path),
                    },
                )
            try:
                findings = scan_document(document, ids)
            except ScanLimitExceeded:
                raise ResultScanRejected("CONTENT_SCAN_LIMIT_EXCEEDED") from None
            for finding in findings:
                body = finding.to_dict()
                body["finding_id"] = new_id()
                views = {
                    sid: document_normalized_view(segment.text)
                    for sid, segment in zip(ids, document.segments)
                }
                self.trace.store_normalized_view(
                    body["spans"][0]["artifact_id"],
                    "\n".join(views[span["artifact_id"]] for span in body["spans"]),
                )
                self.trace.emit(
                    "DETECTION_FINDING",
                    actor_id=actor,
                    parents=[executed_event],
                    action_id=action.to_dict()["action_id"],
                    artifact_ids=[span["artifact_id"] for span in body["spans"]],
                    payload={"finding": body, "kind": "DOCUMENT"},
                )
            artifacts.extend(ids)
        if expose and artifacts:
            self._last_exposure_event = self.trace.emit(
                "MODEL_EXPOSED",
                actor_id=actor,
                parents=[executed_event],
                action_id=action.to_dict()["action_id"],
                artifact_ids=artifacts,
                payload={"tool": tool, "kind": "DOCUMENT"},
            )
            self._exposed_artifacts.update(artifacts)
        return tuple(artifacts)

    def _record_structured_result(
        self,
        tool: str,
        snapshot: ToolResultSnapshot,
        action: SemanticAction,
        executed_event: str,
        content_artifact: str | None,
        *,
        expose: bool,
    ) -> str:
        """One complete source per result; findings refer to encoded field spans.

        Keep the established content artifact for domain-specific oracles and
        exact public-IOC declassification. Other keys/values cannot inherit that
        exception: the complete result remains untrusted, non-transferable data.
        """
        effect = action.to_dict()["effect"]
        actor = self.grant.to_dict()["subject_id"]
        artifact = self.trace.create_artifact(
            snapshot.wire_json,
            source_event_id=executed_event,
            source_id=f"{tool}:structured-result",
            confidentiality="SECRET" if effect["kind"] == "credential.read" else "INTERNAL",
            parents=[content_artifact]
            if content_artifact
            else action.to_dict()["input_artifacts"]
            if tool == "execution.run"
            else [],
            origin_type="MEMORY"
            if tool == "memory.read"
            else "WEB_PAGE"
            if tool == "network.fetch"
            else "MCP_TOOL_RESULT",
        )
        registered = self.trace.emit(
            "CONTENT_REGISTERED",
            actor_id=actor,
            parents=[executed_event],
            action_id=action.to_dict()["action_id"],
            artifact_ids=[artifact],
            payload={
                "tool": tool,
                "kind": "STRUCTURED_TOOL_RESULT",
                "result_binding": {
                    "snapshot_hash": sha(snapshot.wire_json),
                    "utf8_bytes": len(snapshot.wire_json.encode("utf-8")),
                    "fields": [
                        {
                            "path": safe_path(item.path),
                            "kind": item.kind,
                            "wire_start": item.wire_start,
                            "wire_end": item.wire_end,
                            "content_hash": sha(item.text),
                        }
                        for item in snapshot.fields
                    ],
                },
            },
        )
        self.trace.store_normalized_view(artifact, normalized_view(snapshot.wire_json))
        parent = self.trace.emit(
            "CONTENT_NORMALIZED",
            actor_id=actor,
            parents=[registered],
            action_id=action.to_dict()["action_id"],
            artifact_ids=[artifact],
            payload={"detector_version": DETECTOR_VERSION, "kind": "STRUCTURED_TOOL_RESULT"},
        )
        for item in snapshot.fields:
            # The ordinary top-level content has already been scanned once.
            if content_artifact and item.kind == "VALUE" and item.path == ("content",):
                continue
            try:
                view, finding = detect_indirect(
                    item.text,
                    artifact,
                    new_id(),
                    attack_source="MEMORY" if tool == "memory.read" else "INDIRECT",
                )
            except ScanLimitExceeded:
                code = "CONTENT_SCAN_LIMIT_EXCEEDED"
                self.trace.emit(
                    "CONTENT_REGISTERED",
                    actor_id=actor,
                    parents=[parent],
                    action_id=action.to_dict()["action_id"],
                    artifact_ids=[artifact],
                    payload={
                        "tool": tool,
                        "scan_status": "REJECTED",
                        "code": code,
                        "detector_version": DETECTOR_VERSION,
                        "kind": "STRUCTURED_TOOL_RESULT",
                    },
                )
                # Result rejection cannot erase the audit of an effect that ran.
                if effect["side_effect"]:
                    self.trace.emit(
                        "RESOURCE_AFFECTED",
                        actor_id=actor,
                        parents=[executed_event],
                        action_id=action.to_dict()["action_id"],
                        artifact_ids=action.to_dict()["input_artifacts"],
                        payload={"kind": effect["kind"], "resources": effect["resources"]},
                    )
                raise ResultScanRejected(code) from None
            if tool == "memory.read" and finding is None:
                finding = deferred_memory_finding(item.text, view, artifact, new_id())
            if finding is None:
                continue
            body = finding.to_dict()
            body["spans"] = [
                {"artifact_id": artifact, "start": item.wire_start, "end": item.wire_end}
            ]
            finding = DetectionFinding(body)
            parent = self.trace.emit(
                "DETECTION_FINDING",
                actor_id=actor,
                parents=[parent],
                action_id=action.to_dict()["action_id"],
                artifact_ids=[artifact],
                payload={"finding": finding.to_dict(), "kind": "STRUCTURED_TOOL_RESULT"},
            )
        if expose:
            self._last_exposure_event = self.trace.emit(
                "MODEL_EXPOSED",
                actor_id=actor,
                parents=list(dict.fromkeys([parent, self._last_exposure_event]))
                if self._last_exposure_event
                else [parent],
                action_id=action.to_dict()["action_id"],
                artifact_ids=[artifact],
                payload={"tool": tool, "kind": "STRUCTURED_TOOL_RESULT"},
            )
            self._exposed_artifacts.add(artifact)
        return artifact

    def expose_committed_result(self, decision_id: str) -> None:
        """Host hook immediately before an approved result enters model context.

        Merely committing through the operator API is not model exposure. Replays
        can reuse the same source identities without another execution or event.
        """
        pending = self._pending.get(decision_id)
        if pending is None or not (pending.terminal_result or {}).get("ok"):
            raise ValueError("UNCOMMITTED_RESULT")
        identifiers = set(pending.result_artifacts)
        if not identifiers or identifiers <= self._exposed_artifacts:
            return
        parents = [
            self.trace.artifacts[item].to_dict()["origin"]["event_id"] for item in identifiers
        ]
        if self._last_exposure_event:
            parents.append(self._last_exposure_event)
        self._last_exposure_event = self.trace.emit(
            "MODEL_EXPOSED",
            actor_id=self.grant.to_dict()["subject_id"],
            parents=list(dict.fromkeys(parents)),
            action_id=pending.action.to_dict()["action_id"],
            decision_id=decision_id,
            artifact_ids=sorted(identifiers),
            payload={"tool": pending.tool, "kind": "APPROVED_TOOL_RESULT"},
        )
        self._exposed_artifacts.update(identifiers)

    async def _reserve_budget(self, dimension: str) -> bool:
        contract_budget = self.contract.to_dict()["budgets"][dimension]
        grant_budget = self.grant.to_dict()["budgets"].get(dimension, contract_budget)
        limit = min(contract_budget, grant_budget)
        async with self._budget_lock:
            if self._usage[dimension] >= limit:
                return False
            self._usage[dimension] += 1
            return True

    async def approval_summaries(self) -> list[dict[str, Any]]:
        """Metadata for the trusted operator; never expose stored arguments or content."""
        async with self._approval_lock:
            result = []
            for decision_id, pending in self._pending.items():
                if pending.terminal_result is not None:
                    status = (
                        "REJECTED"
                        if pending.terminal_result.get("code") == "APPROVAL_REJECTED"
                        else "CONSUMED"
                        if pending.terminal_result.get("ok")
                        else "FAILED"
                    )
                elif utc_now() >= pending.expires_at:
                    status = "EXPIRED"
                else:
                    status = "APPROVED" if pending.approval is not None else "PENDING"
                action = pending.action.to_dict()
                result.append(
                    {
                        "decision_id": decision_id,
                        "status": status,
                        "tool": pending.tool,
                        "action_id": action["action_id"],
                        "effect": action["effect"],
                        "arguments_hash": action["materialized_args_hash"],
                        "input_content_hash": pending.input_content_hash,
                        "provenance_snapshot_hash": pending.provenance_snapshot_hash,
                        "policy_snapshot_hash": pending.decision.to_dict()["policy_snapshot_hash"],
                        "created_at": utc_text(pending.created_at),
                        "expires_at": utc_text(pending.expires_at),
                        **(
                            {"git_review": dict(pending.review_metadata)}
                            if pending.review_metadata is not None
                            else {}
                        ),
                    }
                )
            return result

    async def reject(self, decision_id: str, principal_id: str) -> dict[str, Any]:
        """A trusted principal can terminate an ASK, including one approved but uncommitted."""
        async with self._approval_lock:
            pending = self._pending.get(decision_id)
            if pending is None:
                return {"ok": False, "code": "APPROVAL_NOT_FOUND"}
            if principal_id != self.contract.to_dict()["principal_id"]:
                return {"ok": False, "code": "APPROVER_MISMATCH"}
            if pending.terminal_result is not None:
                return {"ok": False, "code": "APPROVAL_ALREADY_TERMINAL"}
            pending.terminal_result = {
                "ok": False,
                "decision": "BLOCK",
                "code": "APPROVAL_REJECTED",
            }
            self.trace.emit(
                "APPROVAL_RECORDED",
                actor_id=principal_id,
                parents=[pending.requested_event_id],
                action_id=pending.action.to_dict()["action_id"],
                decision_id=decision_id,
                payload={"status": "REJECTED"},
            )
            return {"ok": True, "decision_id": decision_id, "status": "REJECTED"}

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
            if pending.tool == "git_delivery.push" and not await self._git_state_matches(
                pending.requested_event_id
            ):
                return {"ok": False, "code": "APPROVAL_STALE"}
            approval = ApprovalRecord(
                {
                    "schema_version": "1.0",
                    "approval_id": new_id(),
                    "decision_id": decision_id,
                    "approved_by": principal_id,
                    "binding": make_binding(
                        pending.action,
                        self.contract,
                        self.grant,
                        input_content_hash=pending.input_content_hash,
                        provenance_snapshot_hash=pending.provenance_snapshot_hash,
                    ),
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
            arguments = load_json(pending.arguments_json)
            artifact_ids = pending.action.to_dict()["input_artifacts"]
            if (
                self._input_content_hash(arguments) != pending.input_content_hash
                or self._provenance_hash(artifact_ids) != pending.provenance_snapshot_hash
            ):
                return {"ok": False, "code": "APPROVAL_STALE"}
            if not approval_is_valid(
                pending.approval,
                pending.decision,
                pending.action,
                self.contract,
                self.grant,
                now=now,
                input_content_hash=pending.input_content_hash,
                provenance_snapshot_hash=pending.provenance_snapshot_hash,
            ):
                return {"ok": False, "code": "APPROVAL_STALE"}

            try:
                fresh = semantic_action(
                    pending.tool,
                    arguments,
                    self.proxy.registry[pending.tool],
                    self.contract,
                    self.grant,
                    input_artifacts=artifact_ids,
                    sensitive_resources=self.sensitive_resources,
                    network_policy=self.network_policy,
                    execution_policy=self.execution_policy,
                    git_policy=self.git_policy,
                    memory_policy=self.memory_policy,
                )
            except (KeyError, TypeError, ValueError):
                return {"ok": False, "code": "APPROVAL_STALE"}
            fresh_body = fresh.to_dict()
            fresh_body["action_id"] = pending.action.to_dict()["action_id"]
            if sha(fresh_body) != sha(pending.action.to_dict()):
                return {"ok": False, "code": "APPROVAL_STALE"}
            if self.policy.decide(fresh, self.contract, self.grant).decision != "ASK":
                return {"ok": False, "code": "APPROVAL_STALE"}
            if pending.tool == "git_delivery.push" and not await self._git_state_matches(
                pending.requested_event_id
            ):
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
                data = await self.proxy.invoke(pending.tool, arguments)
                result_snapshot = snapshot_tool_result(data)
                data = result_snapshot.payload()
                result = {
                    "ok": True,
                    "decision": "ASK",
                    "approved": True,
                    "data": data,
                    "replayed": False,
                }
            except RuntimeError as error:
                result = {
                    "ok": False,
                    "decision": "ASK",
                    "approved": True,
                    "code": str(error)
                    if isinstance(error, ToolResultError)
                    else "TOOL_EXECUTION_FAILED",
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
                payload={"tool": pending.tool, "ok": result["ok"]},
            )
            if result["ok"]:
                self._track_file_write(pending.tool, arguments, pending.action, executed)
                try:
                    pending.result_artifacts = self._record_tool_result(
                        pending.tool,
                        result["data"],
                        pending.action,
                        executed,
                        expose=False,
                        snapshot=result_snapshot,
                    )
                except ResultScanRejected as rejected:
                    result = {
                        "ok": False,
                        "decision": "ASK",
                        "approved": True,
                        "code": rejected.code,
                        "replayed": False,
                    }
                    pending.terminal_result = result
            return result
