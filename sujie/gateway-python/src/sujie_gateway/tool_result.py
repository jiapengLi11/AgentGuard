"""Bounded JSON result snapshots, including text in object keys and nested values."""

from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass, field
from typing import Any

from .doc_parsing import document_type

MAX_RESULT_BYTES = 262_144
MAX_RESULT_DEPTH = 16
MAX_RESULT_NODES = 4096
MAX_RESULT_FIELDS = 256


class ToolResultError(RuntimeError):
    """Constant codes only: rejected result content must not enter errors or models."""


@dataclass(frozen=True)
class ResultTextField:
    path: tuple[str | int, ...]
    kind: str
    text: str = field(repr=False)
    wire_start: int
    wire_end: int


@dataclass(frozen=True)
class ToolResultSnapshot:
    wire_json: str = field(repr=False)
    fields: tuple[ResultTextField, ...]

    def payload(self) -> dict[str, Any]:
        return json.loads(self.wire_json)


def snapshot_tool_result(value: dict[str, Any]) -> ToolResultSnapshot:
    """Freeze exactly the JSON returned to the Host; never silently truncate text.

    Offsets cover the encoded string token's contents in wire_json, not positions
    in a decoded/normalized field. Object keys are text too. Validation completes
    before callers register any field or expose any portion of this result.
    """
    if not isinstance(value, dict):
        raise ToolResultError("TOOL_RESULT_INVALID")
    chunks, fields = [], []
    characters = byte_count = nodes = 0

    def emit(fragment: str) -> None:
        nonlocal characters, byte_count
        try:
            byte_count += len(fragment.encode("utf-8"))
        except UnicodeError:
            raise ToolResultError("TOOL_RESULT_INVALID") from None
        if byte_count > MAX_RESULT_BYTES:
            raise ToolResultError("TOOL_RESULT_SIZE_LIMIT")
        chunks.append(fragment)
        characters += len(fragment)

    def text(raw: str, path: tuple[str | int, ...], kind: str) -> None:
        if len(fields) >= MAX_RESULT_FIELDS:
            raise ToolResultError("TOOL_RESULT_FIELD_LIMIT")
        if len(raw) > MAX_RESULT_BYTES:
            raise ToolResultError("TOOL_RESULT_SIZE_LIMIT")
        start = characters + 1
        emit(json.dumps(raw, ensure_ascii=False))
        fields.append(ResultTextField(path, kind, raw, start, characters - 1))

    def visit(item: Any, path: tuple[str | int, ...], depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_RESULT_NODES:
            raise ToolResultError("TOOL_RESULT_NODE_LIMIT")
        if depth > MAX_RESULT_DEPTH:
            raise ToolResultError("TOOL_RESULT_DEPTH_LIMIT")
        if isinstance(item, str):
            text(item, path, "VALUE")
        elif isinstance(item, bytes):
            if len(item) > MAX_RESULT_BYTES:
                raise ToolResultError("TOOL_RESULT_SIZE_LIMIT")
            if not document_type(item):
                raise ToolResultError("TOOL_RESULT_INVALID")
            text(base64.b64encode(item).decode("ascii"), path, "VALUE")
        elif isinstance(item, dict):
            emit("{")
            for index, (key, child) in enumerate(item.items()):
                if not isinstance(key, str):
                    raise ToolResultError("TOOL_RESULT_INVALID")
                if index:
                    emit(", ")
                text(key, (*path, key), "KEY")
                emit(": ")
                visit(child, (*path, key), depth + 1)
            emit("}")
        elif isinstance(item, list):
            emit("[")
            for index, child in enumerate(item):
                if index:
                    emit(", ")
                visit(child, (*path, index), depth + 1)
            emit("]")
        elif item is None or type(item) in {bool, int}:
            emit(json.dumps(item))
        elif type(item) is float and math.isfinite(item):
            emit(json.dumps(item, allow_nan=False))
        else:
            raise ToolResultError("TOOL_RESULT_INVALID")

    try:
        visit(value, (), 0)
    except (ValueError, TypeError, RecursionError):
        raise ToolResultError("TOOL_RESULT_INVALID") from None
    return ToolResultSnapshot("".join(chunks), tuple(fields))
