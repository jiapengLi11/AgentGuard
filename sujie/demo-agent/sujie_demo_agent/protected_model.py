"""One guarded model interface for Host, classification, analysis and child roles."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import asdict

from sujie_gateway.model_context import (
    ContextError,
    ContextSource,
    ModelEgressPolicy,
    build_snapshot,
    canonical,
    contains_protected,
    digest,
    safe_path,
)

from .bailian_agent import ChatModel, ModelProtocolError
from .model_budget import BudgetError, ModelBudget
from .tokenizer_mapper import LocalTokenMapper

PURPOSES = frozenset({"MAIN", "CLASSIFY", "ISOLATED_ANALYSIS", "SUBAGENT", "RECOVERY"})


class ProtectedModel:
    """Bound by trusted Python configuration, never by model-supplied annotations."""

    def __init__(
        self,
        model: ChatModel,
        gateway,
        *,
        protected_values: tuple[str, ...] = (),
        purpose: str = "MAIN",
        tokenizer: LocalTokenMapper | None = None,
        budget: ModelBudget | None = None,
    ):
        if purpose not in PURPOSES:
            raise ValueError("INVALID_MODEL_PURPOSE")
        self._model, self.gateway, self.purpose = model, gateway, purpose
        self.policy = ModelEgressPolicy(protected_values=protected_values)
        self.tokenizer = tokenizer
        self.budget = budget or ModelBudget()
        self.forwarded_requests = 0
        self.blocked_requests = 0
        self.response_blocks = 0
        self.response_artifacts: tuple[str, ...] | None = None
        self.response_event_id: str | None = None
        self._assistant_bindings: dict[tuple[int, str, str], tuple[str, ...]] = {}

    @property
    def model(self):
        return getattr(self._model, "model", "scripted-test-model")

    @property
    def max_tokens(self):
        return getattr(self._model, "max_tokens", 512)

    @property
    def usage(self):
        return getattr(self._model, "usage", [])

    def for_purpose(self, purpose: str) -> ProtectedModel:
        return ProtectedModel(
            self._model,
            self.gateway,
            protected_values=self.policy.protected_values,
            purpose=purpose,
            tokenizer=self.tokenizer,
            budget=self.budget,
        )

    def _sources(self) -> tuple[ContextSource, ...]:
        return tuple(
            ContextSource(
                identifier,
                self.gateway.trace.artifact_contents[identifier],
                self.gateway.trace.artifacts[identifier].to_dict()["confidentiality"],
                self.gateway.trace.artifacts[identifier].to_dict()["origin"]["type"],
                tuple(self.gateway.trace.artifacts[identifier].to_dict()["allowed_uses"]),
                tuple(self.gateway.trace.artifacts[identifier].to_dict()["forbidden_uses"]),
            )
            for identifier in sorted(self.gateway._exposed_artifacts)
        )

    def _emit(self, event: str, payload: dict, artifacts=(), *, parents=None) -> str:
        return self.gateway.trace.emit(
            event,
            actor_id=self.gateway.grant.to_dict()["subject_id"],
            parents=parents
            if parents is not None
            else ([self.gateway._last_exposure_event] if self.gateway._last_exposure_event else []),
            artifact_ids=list(artifacts),
            payload={"purpose": self.purpose, **payload},
        )

    @staticmethod
    def _prefixes(messages: list[dict]) -> list[str]:
        prefix = hashlib.sha256(b"sujie-conversation-prefix-v1")
        result = []
        for message in messages:
            result.append(prefix.hexdigest())
            raw = canonical(message).encode("utf-8")
            prefix.update(str(len(raw)).encode() + b":" + raw)
        result.append(prefix.hexdigest())
        return result

    async def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        try:
            sources = self._sources()
            prefixes = self._prefixes(messages)
            # Unknown caller-supplied rewrites inherit exposure. Responses actually
            # observed by this wrapper bind to their request's sources, so later
            # reads cannot retroactively taint earlier assistant messages.
            inherited = {
                index: self._assistant_bindings.get(
                    (index, digest(canonical(message)), prefixes[index]),
                    tuple(source.artifact_id for source in sources),
                )
                for index, message in enumerate(messages)
                if message.get("role") == "assistant"
            }
            snapshot = build_snapshot(
                messages, tools, sources=sources, inherited_by_message=inherited
            )
            self.policy.check(snapshot)
            mapping = (
                self.tokenizer.map(snapshot)
                if self.tokenizer
                else {
                    "status": "UNAVAILABLE",
                    "provider_tokenization": "UNKNOWN",
                    "fields": [],
                }
            )
        except ContextError as error:
            self.blocked_requests += 1
            self._emit("MODEL_EGRESS_BLOCKED", {"code": str(error), "direction": "REQUEST"})
            raise ModelProtocolError(str(error)) from None
        metadata = {
            "request_hash": snapshot.request_hash,
            "fields": [
                {
                    "field_index": item.index,
                    "path": safe_path(item.path),
                    "characters": len(item.text),
                    "source_spans": [asdict(span) for span in item.spans],
                    "inherited_artifacts": list(item.inherited_artifacts),
                }
                for item in snapshot.fields
            ],
            "token_mapping": mapping,
            "assistant_lineage": "REQUEST_BOUND_WITH_PREFIX_VALIDATION",
        }
        request_event = self._emit("MODEL_REQUEST_CHECKED", metadata, snapshot.referenced_artifacts)
        payload = snapshot.payload()
        try:
            # JSON bytes plus output allowance and a template reserve are an
            # estimate only. Cloud billing/tokenization are not observable here.
            units = len(snapshot.wire_json.encode("utf-8")) + self.max_tokens + 512
            ticket = self.budget.reserve(self.purpose, units)
        except BudgetError as error:
            self.blocked_requests += 1
            self._emit("MODEL_EGRESS_BLOCKED", {"code": str(error), "direction": "REQUEST"})
            raise ModelProtocolError(str(error)) from None
        self.forwarded_requests += 1
        usage_before = len(self.usage)
        status = "FAILED"
        try:
            response = await self._model.complete(payload["messages"], payload["tools"])
            status = "RETURNED"
        except asyncio.CancelledError:
            status = "CANCELLED"
            raise
        finally:
            reported = []
            for row in self.usage[usage_before:]:
                value = row.get("total_tokens") if isinstance(row, dict) else None
                if type(value) is int and 0 <= value <= 1_000_000_000:
                    reported.append(value)
                else:
                    reported = []
                    break
            try:
                self.budget.settle(
                    ticket, status=status, reported_tokens=sum(reported) if reported else None
                )
            except BudgetError as error:
                raise ModelProtocolError(str(error)) from None
        try:
            # Check full response, including tool argument strings and encoded values.
            forbidden = self.policy.protected_values + tuple(
                source.text
                for source in self._sources()
                if source.confidentiality not in self.policy.allowed_confidentialities
            )
            if contains_protected(response, forbidden):
                raise ContextError("MODEL_OUTPUT_PROTECTED_VALUE")
        except ContextError as error:
            self.response_blocks += 1
            self._emit("MODEL_EGRESS_BLOCKED", {"code": str(error), "direction": "RESPONSE"})
            raise ModelProtocolError(str(error)) from None
        self.response_event_id = self._emit(
            "MODEL_RESPONSE_CHECKED",
            {"request_hash": snapshot.request_hash, "code": "RESPONSE_ACCEPTED"},
            snapshot.referenced_artifacts,
            parents=[request_event],
        )
        content = response.get("content") or ""
        calls = response.get("tool_calls") or []
        if isinstance(content, str) and isinstance(calls, list):
            normalized = {"role": "assistant", "content": content}
            if calls:
                normalized["tool_calls"] = calls
            audited_messages = snapshot.payload()["messages"]
            self._assistant_bindings[
                len(audited_messages),
                digest(canonical(normalized)),
                self._prefixes(audited_messages)[-1],
            ] = snapshot.referenced_artifacts
        self.response_artifacts = snapshot.referenced_artifacts
        return response
