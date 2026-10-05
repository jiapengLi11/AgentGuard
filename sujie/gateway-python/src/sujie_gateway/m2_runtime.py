"""M2 ingress, exposure, effect gating and redacted provenance on the existing M1 boundary."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

from .contracts import SemanticAction, TaskContract, TaskGrant, canonical_json, load_json
from .invariants import CONFIDENTIALITY, assert_use
from .m1_runtime import GateDecision, M1Gateway, M1Policy, StdioMCPProxy, sha
from .provenance import ArtifactRegistry, ProvenanceError, ResourceProfile

FIELDS = {
    "evidence.read_alert": {"alert_id"},
    "operations.read_file": {"resource"},
    "operations.write_file": {"resource", "content"},
    "operations.send_data": {"destination", "content"},
}


class M2Gateway(M1Gateway):
    """Internal registry/labels are trusted configuration, not Agent-provided capabilities."""

    def __init__(
        self,
        proxy: StdioMCPProxy,
        contract: TaskContract,
        grant: TaskGrant,
        *,
        resource_profiles: dict[str, str | ResourceProfile],
    ) -> None:
        super().__init__(proxy, contract, grant)
        self.policy = M1Policy("m2.yaml")
        self._owner = self._context()
        self.registry = ArtifactRegistry(
            (self._owner[0], self._owner[2], self._owner[3]), self._emit_provenance
        )
        self._profiles = MappingProxyType(
            {
                key: ResourceProfile(value)
                if isinstance(value, str)
                else ResourceProfile(value.confidentiality, tuple(value.allowed_uses))
                for key, value in resource_profiles.items()
            }
        )
        self._read_bindings: dict[str, str] = {}
        self._content_bindings: dict[str, tuple[str, str]] = {}
        self._files: dict[str, str] = {}
        self._actions: dict[str, dict] = {}

    def _context(self) -> tuple[str, str, str, str]:
        c, g = self.contract.to_dict(), self.grant.to_dict()
        return c["contract_id"], c["principal_id"], c["session_id"], g["subject_id"]

    def _emit_provenance(self, kind: str, ids: list[str], parents: list[str]) -> str:
        return self.trace.emit(
            kind,
            actor_id=self.grant.to_dict()["subject_id"],
            artifact_ids=ids,
            parents=parents,
            payload={"artifact_ids": ids},
        )

    def _profile(self, key: str) -> ResourceProfile:
        configured = self._profiles.get(key)
        file_parent = self._files.get(key)
        if file_parent is None:
            if configured is None:
                raise ProvenanceError("UNCLASSIFIED_SOURCE")
            return configured
        body = self.registry.envelope(file_parent).to_dict()
        level = max(
            [body["confidentiality"]] + ([configured.confidentiality] if configured else []),
            key=CONFIDENTIALITY.__getitem__,
        )
        uses = set(body["allowed_uses"])
        if configured:
            uses.intersection_update(configured.allowed_uses)
        return ResourceProfile(level, tuple(sorted(uses)))

    def _make_action(
        self, tool: str, arguments: dict[str, Any], *, input_artifacts: list[str] | None = None
    ) -> SemanticAction:
        if self._context() != self._owner:
            raise ProvenanceError("PROVENANCE_CONTEXT_MISMATCH")
        if (
            tool not in FIELDS
            or set(arguments) != FIELDS[tool]
            or any(not isinstance(v, str) for v in arguments.values())
        ):
            raise ProvenanceError("INVALID_M2_ARGUMENTS")
        ids = []
        if "content" in arguments:
            if input_artifacts is None:
                ids = [self.registry.generate(arguments["content"])]
            else:
                ids = list(input_artifacts)
                if len(ids) != 1 or self.registry.text(ids[0]) != arguments["content"]:
                    raise ProvenanceError("MATERIALIZED_CONTENT_MISMATCH")
        action = super()._make_action(tool, arguments, input_artifacts=ids)
        artifact_id = action.to_dict()["action_id"]
        if ids:
            self._content_bindings[artifact_id] = (ids[0], sha(arguments))
        if tool in {"evidence.read_alert", "operations.read_file"}:
            self._read_bindings[artifact_id] = (
                ("evidence:" + arguments["alert_id"])
                if tool == "evidence.read_alert"
                else ("operations:" + arguments["resource"])
            )
        return action

    def _facts(self, action: SemanticAction) -> dict:
        a = action.to_dict()
        artifact_ids, kind = a["input_artifacts"], a["effect"]["kind"]
        if kind == "file.read":
            if (
                "READ" not in self._profile(self._read_bindings[a["action_id"]]).allowed_uses
                or "READ" not in self.contract.to_dict()["allowed_purposes"]
            ):
                raise ProvenanceError("SOURCE_READ_NOT_ALLOWED")
        if kind in {"file.write", "data.transfer"}:
            binding = self._content_bindings.get(a["action_id"])
            if (
                binding is None
                or artifact_ids != [binding[0]]
                or binding[1] != a["materialized_args_hash"]
            ):
                raise ProvenanceError("MISSING_CONTENT_BINDING")
            if not set(self.registry.exposed) <= self.registry.ancestors(artifact_ids):
                raise ProvenanceError("EXPOSURE_CHANGED")
            for artifact_id in artifact_ids:
                purpose = "TRANSFER" if kind == "data.transfer" else "QUOTE"
                if purpose not in self.contract.to_dict()["allowed_purposes"]:
                    raise ProvenanceError("PURPOSE_OUTSIDE_CONTRACT")
                assert_use(self.registry.envelope(artifact_id), purpose)
        return {
            "max_confidentiality": max(
                (
                    CONFIDENTIALITY[self.registry.envelope(p).to_dict()["confidentiality"]]
                    for p in artifact_ids
                ),
                default=0,
            )
        }

    def _decide(self, action: SemanticAction) -> GateDecision:
        try:
            if self._context() != self._owner:
                raise ProvenanceError("PROVENANCE_CONTEXT_MISMATCH")
            if self.contract.to_dict()["policy_snapshot_hash"] != self.policy.snapshot_hash:
                raise ProvenanceError("POLICY_SNAPSHOT_MISMATCH")
            facts = self._facts(action)
            self.registry.binding_hashes(action.to_dict()["input_artifacts"])
            decision = self.policy.decide(
                action,
                self.contract,
                self.grant,
                contract_usage=self._contract_usage.get(self.contract.to_dict()["contract_id"], {}),
                grant_usage=self._grant_usage.get(self.grant.to_dict()["grant_id"], {}),
                data_facts=facts,
            )
        except (ValueError, KeyError) as error:
            decision = GateDecision(
                "BLOCK",
                True,
                str(error) if isinstance(error, ValueError) else "PROVENANCE_REJECTED",
                action,
            )
        if action.to_dict()["action_id"] in self._actions:
            self._actions[action.to_dict()["action_id"]].update(
                decision=decision.decision, reason=decision.reason, hard_block=decision.hard_block
            )
        return decision

    def _input_hashes(self, action: SemanticAction) -> tuple[str, str]:
        try:
            return self.registry.binding_hashes(action.to_dict()["input_artifacts"])
        except ValueError:
            # A vanished/corrupt dependency cannot produce the old successful binding.
            rejected = sha({"invalid_provenance": True})
            return rejected, rejected

    def _record_decision(
        self, action: SemanticAction, decision: GateDecision, decision_id: str
    ) -> None:
        a = action.to_dict()
        self._actions[a["action_id"]] = {
            "id": a["action_id"],
            "kind": "action",
            "effect": a["effect"]["kind"],
            "tool_name": a["tool_identity"]["tool_name"],
            "server_id": a["tool_identity"]["server_id"],
            "policy_snapshot_hash": self.policy.snapshot_hash,
            "evaluated_authority_refs": [f"contract:{a['contract_id']}", f"grant:{a['grant_id']}"],
            "decision": decision.decision,
            "hard_block": decision.hard_block,
            "reason": decision.reason,
            "decision_id": decision_id,
            "input_artifacts": a["input_artifacts"],
            "executed": False,
            "resource_refs": ["resource:" + sha(resource) for resource in a["effect"]["resources"]],
        }

    def _after_result(
        self,
        action: SemanticAction,
        tool: str,
        arguments: dict[str, Any],
        data: dict[str, Any],
        event_id: str,
    ) -> dict[str, Any]:
        a = action.to_dict()
        self._actions[a["action_id"]]["executed"] = True
        parent = None
        if tool in {"evidence.read_alert", "operations.read_file"}:
            source = self._read_bindings[a["action_id"]]
            profile = self._profile(source)
            parent = self._files.get(source)
        else:
            parent = a["input_artifacts"][0]
            body = self.registry.envelope(parent).to_dict()
            profile = ResourceProfile(body["confidentiality"], tuple(body["allowed_uses"]))
            source = tool
            if tool == "operations.write_file":
                self._files["operations:" + arguments["resource"]] = parent
        ids = self.registry.register_mcp(
            data, source_id=source, profile=profile, source_event_id=event_id, file_parent=parent
        )
        if a["effect"]["kind"] == "file.read":
            self._actions[a["action_id"]]["read_artifacts"] = ids
        if a["effect"]["side_effect"]:
            self.trace.emit(
                "RESOURCE_AFFECTED",
                actor_id=a["subject_id"],
                action_id=a["action_id"],
                parents=[event_id],
                artifact_ids=a["input_artifacts"],
                payload={"resource_refs": self._actions[a["action_id"]]["resource_refs"]},
            )
        fields = {}
        for artifact_id in ids:
            transforms = self.registry.envelope(artifact_id).to_dict()["transformations"]
            if transforms and transforms[0]["mapping_ref"]:
                mapping = self.registry.mapping(transforms[0]["mapping_ref"])
                if mapping.get("kind") == "JSON_FIELD":
                    pointer = "/" + "/".join(
                        str(p).replace("~", "~0").replace("/", "~1") for p in mapping["path"]
                    )
                    fields[pointer] = artifact_id
        return {"artifact_ids": ids, "field_artifacts": fields}

    def dag(self) -> dict:
        if self._context() != self._owner:
            raise ProvenanceError("PROVENANCE_CONTEXT_MISMATCH")
        graph = self.registry.redacted_graph()
        nodes, edges = graph["nodes"], graph["edges"]
        subject = f"subject:{self.grant.to_dict()['subject_id']}"
        c, g = self.contract.to_dict(), self.grant.to_dict()
        authority_nodes = [f"contract:{c['contract_id']}", f"grant:{g['grant_id']}"]
        authority_nodes = sorted(
            set(authority_nodes)
            | {p for action in self._actions.values() for p in action["evaluated_authority_refs"]}
        )
        nodes.extend({"id": p, "kind": p.split(":", 1)[0]} for p in authority_nodes)
        resources = set()
        for action in self._actions.values():
            nodes.append(dict(action))
            edges.append(
                {
                    "source": subject,
                    "target": action["id"],
                    "type": "PROPOSED",
                    "certainty": "observed",
                }
            )
            edges.extend(
                {
                    "source": p,
                    "target": action["id"],
                    "type": "PROPOSED",
                    "certainty": "conservative",
                }
                for p in action["input_artifacts"]
            )
            edges.extend(
                {"source": p, "target": action["id"], "type": "READ_FROM", "certainty": "observed"}
                for p in action.get("read_artifacts", [])
            )
            if action["executed"]:
                edges.extend(
                    {
                        "source": action["id"],
                        "target": p,
                        "type": "AUTHORIZED_BY",
                        "certainty": "observed",
                    }
                    for p in action["evaluated_authority_refs"]
                )
                for resource in action["resource_refs"]:
                    resources.add(resource)
                    edges.append(
                        {
                            "source": action["id"],
                            "target": resource,
                            "type": "AFFECTED" if action["effect"] != "file.read" else "EXECUTED",
                            "certainty": "observed",
                        }
                    )
        nodes.extend({"id": p, "kind": "resource"} for p in sorted(resources))
        return load_json(
            canonical_json(
                {
                    "context": {"contract_id": c["contract_id"], "subject_id": g["subject_id"]},
                    **graph,
                }
            )
        )
