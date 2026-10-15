"""Immutable model request evidence and deterministic outbound data policy."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

MAX_REQUEST_BYTES = 262_144
LEVELS = frozenset({"PUBLIC", "INTERNAL", "CONFIDENTIAL", "SECRET"})


class ContextError(ValueError):
    """Only constant codes; never reflect request bodies or secret values."""


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(value: Any) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        text.encode("utf-8")
        return text
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise ContextError("MODEL_CONTEXT_INVALID") from None


@dataclass(frozen=True)
class ContextSource:
    artifact_id: str
    text: str = field(repr=False)
    confidentiality: str = "INTERNAL"
    origin_type: str = "MCP_TOOL_RESULT"
    allowed_uses: tuple[str, ...] = ("ANALYZE",)
    forbidden_uses: tuple[str, ...] = ()

    def __post_init__(self):
        if (
            not isinstance(self.artifact_id, str)
            or not 1 <= len(self.artifact_id) <= 128
            or not isinstance(self.text, str)
            or len(self.text) > MAX_REQUEST_BYTES
            or self.confidentiality not in LEVELS
        ):
            raise ContextError("MODEL_SOURCE_INVALID")
        try:
            self.text.encode("utf-8")
        except UnicodeError:
            raise ContextError("MODEL_SOURCE_INVALID") from None


@dataclass(frozen=True)
class SourceSpan:
    start: int
    end: int
    artifact_id: str
    source_start: int
    source_end: int
    mapping: str


@dataclass(frozen=True)
class TextField:
    index: int
    path: tuple[str | int, ...]
    text: str = field(repr=False)
    spans: tuple[SourceSpan, ...] = ()
    inherited_artifacts: tuple[str, ...] = ()


@dataclass(frozen=True)
class RequestSnapshot:
    wire_json: str = field(repr=False)
    fields: tuple[TextField, ...]
    sources: tuple[ContextSource, ...]

    def payload(self) -> dict:
        # A fresh copy prevents a caller from mutating the audited request after a wait.
        return json.loads(self.wire_json)

    @property
    def request_hash(self) -> str:
        return digest(self.wire_json)

    @property
    def referenced_artifacts(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    sid
                    for item in self.fields
                    for sid in (
                        *item.inherited_artifacts,
                        *(span.artifact_id for span in item.spans),
                    )
                }
            )
        )


def _text_fields(value, path=(), *, depth=0):
    if depth > 16:
        raise ContextError("MODEL_CONTEXT_DEPTH_LIMIT")
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _text_fields(child, (*path, index), depth=depth + 1)
    elif isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ContextError("MODEL_CONTEXT_INVALID")
            yield from _text_fields(child, (*path, key), depth=depth + 1)
    elif value is not None and type(value) not in {int, float, bool}:
        raise ContextError("MODEL_CONTEXT_INVALID")


def _json_escape_map(text: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    fragments, offsets, position = [], [], 0
    for char in text:
        fragment = json.dumps(char, ensure_ascii=False)[1:-1]
        fragments.append(fragment)
        offsets.append((position, position + len(fragment)))
        position += len(fragment)
    return "".join(fragments), tuple(offsets)


def _spans(text: str, source: ContextSource, escape_map) -> list[SourceSpan]:
    if not source.text:
        return []
    result = []
    escaped, offsets = escape_map
    # When escaping changes text, each character has its own exact origin range.
    for needle, mapping in ((source.text, "EXACT_LITERAL"), (escaped, "JSON_ESCAPE")):
        if mapping == "JSON_ESCAPE" and needle == source.text:
            continue
        position = 0
        while True:
            start = text.find(needle, position)
            if start < 0:
                break
            if mapping == "EXACT_LITERAL":
                result.append(
                    SourceSpan(
                        start, start + len(needle), source.artifact_id, 0, len(source.text), mapping
                    )
                )
            else:
                for index, (begin, end) in enumerate(offsets):
                    result.append(
                        SourceSpan(
                            start + begin,
                            start + end,
                            source.artifact_id,
                            index,
                            index + 1,
                            mapping,
                        )
                    )
            position = start + len(needle)
            if len(result) > MAX_REQUEST_BYTES:
                raise ContextError("MODEL_SOURCE_SPAN_LIMIT")
    return result


def build_snapshot(
    messages: list[dict],
    tools: list[dict],
    *,
    sources: tuple[ContextSource, ...] = (),
    inherited_by_message: dict[int, tuple[str, ...]] | None = None,
) -> RequestSnapshot:
    if (
        not isinstance(messages, list)
        or not 1 <= len(messages) <= 128
        or not isinstance(tools, list)
    ):
        raise ContextError("MODEL_CONTEXT_INVALID")
    if (
        len(tools) > 128
        or len(sources) > 256
        or len({s.artifact_id for s in sources}) != len(sources)
    ):
        raise ContextError("MODEL_CONTEXT_LIMIT")
    inherited = inherited_by_message or {}
    known = {source.artifact_id for source in sources}
    if any(
        type(index) is not int or not 0 <= index < len(messages) or not set(ids) <= known
        for index, ids in inherited.items()
    ):
        raise ContextError("MODEL_SOURCE_INVALID")
    for message in messages:
        if (
            not isinstance(message, dict)
            or message.get("role") not in {"system", "user", "assistant", "tool"}
            or (message.get("content") is not None and not isinstance(message.get("content"), str))
        ):
            raise ContextError("MODEL_CONTEXT_INVALID")
    original = {"messages": messages, "tools": tools}
    # Validate nesting before serialization (no implicit key/type coercion).
    list(_text_fields(original))
    wire = canonical(original)
    if len(wire.encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ContextError("MODEL_CONTEXT_SIZE_LIMIT")
    payload = json.loads(wire)
    escape_maps = {source.artifact_id: _json_escape_map(source.text) for source in sources}
    fields = []
    for index, (path, text) in enumerate(_text_fields(payload)):
        spans = [
            span
            for source in sources
            for span in _spans(text, source, escape_maps[source.artifact_id])
        ]
        parents = inherited.get(path[1], ()) if path[0] == "messages" else ()
        fields.append(TextField(index, path, text, tuple(spans), tuple(sorted(set(parents)))))
    return RequestSnapshot(wire, tuple(fields), sources)


def encoded_variants(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    raw = value.encode("utf-8")
    escaped = json.dumps(value, ensure_ascii=False)[1:-1]
    ascii_escaped = json.dumps(value, ensure_ascii=True)[1:-1]
    return tuple(
        sorted(
            {
                value,
                escaped,
                ascii_escaped,
                json.dumps(escaped, ensure_ascii=False)[1:-1],
                quote(value, safe=""),
                quote(quote(value, safe=""), safe=""),
                base64.b64encode(raw).decode(),
                base64.urlsafe_b64encode(raw).decode(),
                raw.hex(),
                raw.hex().upper(),
            }
        )
    )


def contains_protected(value: Any, protected_values: tuple[str, ...]) -> bool:
    # The serialized view also scans dictionary keys; raw fields cover JSON escaping.
    strings = [canonical(value), *(text for _, text in _text_fields(value))]
    return any(
        needle in text
        for secret in protected_values
        for needle in encoded_variants(secret)
        for text in strings
    )


@dataclass(frozen=True)
class ModelEgressPolicy:
    allowed_confidentialities: frozenset[str] = frozenset({"PUBLIC", "INTERNAL"})
    protected_values: tuple[str, ...] = field(default=(), repr=False)

    def check(self, snapshot: RequestSnapshot) -> None:
        if not self.allowed_confidentialities <= LEVELS:
            raise ContextError("MODEL_POLICY_INVALID")
        if contains_protected(snapshot.payload(), self.protected_values):
            raise ContextError("MODEL_EGRESS_PROTECTED_VALUE")
        used = set(snapshot.referenced_artifacts)
        for source in snapshot.sources:
            if source.artifact_id in used and (
                "ANALYZE" not in source.allowed_uses or "ANALYZE" in source.forbidden_uses
            ):
                raise ContextError("MODEL_EGRESS_PURPOSE")
            if source.confidentiality not in self.allowed_confidentialities:
                if source.artifact_id in used or contains_protected(
                    snapshot.payload(), (source.text,)
                ):
                    raise ContextError("MODEL_EGRESS_CLASSIFICATION")


def safe_path(path: tuple[str | int, ...]) -> list[str | int]:
    # Arbitrary schema keys can themselves contain protected values. Hash unknown keys.
    labels = {
        "messages",
        "tools",
        "content",
        "role",
        "tool_calls",
        "tool_call_id",
        "id",
        "function",
        "name",
        "arguments",
        "parameters",
        "type",
        "description",
        "properties",
        "required",
        "enum",
        "items",
        "additionalProperties",
    }
    return [
        part if isinstance(part, int) or part in labels else "key:" + digest(part)[7:23]
        for part in path
    ]
