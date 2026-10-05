"""Immutable content, monotone exposure and conservative ordinary derivations."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher

from ..contracts import ProvenanceEnvelope, canonical_json, snapshot_hash
from ..identifiers import new_id
from ..invariants import CONFIDENTIALITY, assert_ordinary_derivation, assert_use

DEFAULT_USES = ("READ", "ANALYZE", "QUOTE", "STORE_EVIDENCE", "TRANSFER")
FORBIDDEN = ("AUTHORIZE", "EXECUTE", "CHANGE_POLICY")
MAX_BYTES = 262144
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_MAPPING_BYTES = 4 * 1024 * 1024
MAX_ARTIFACTS = 1024
MAX_PARENTS = 256
MAX_DEPTH = 32


class ProvenanceError(ValueError):
    """Only constant failure codes; untrusted content is never reflected."""


@dataclass(frozen=True)
class ResourceProfile:
    confidentiality: str
    allowed_uses: tuple[str, ...] = DEFAULT_USES

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_uses", tuple(self.allowed_uses))
        if self.confidentiality not in CONFIDENTIALITY or not set(self.allowed_uses) <= set(
            DEFAULT_USES
        ):
            raise ProvenanceError("INVALID_RESOURCE_PROFILE")


@dataclass(frozen=True, repr=False)
class Artifact:
    content: bytes
    envelope: ProvenanceEnvelope


def content_hash(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def span(source_start: int, source_end: int, view_start: int, view_end: int) -> dict:
    return dict(
        source_start=source_start, source_end=source_end, view_start=view_start, view_end=view_end
    )


class ArtifactRegistry:
    """One trusted task/subject context. Labels and exposure cannot be set through tools."""

    def __init__(self, context: tuple[str, str, str], emit: Callable | None = None) -> None:
        self.context = context
        self._emit = emit
        self._records: dict[str, Artifact] = {}
        self._mappings: dict[str, str] = {}
        self._restrictions: dict[str, tuple[str, frozenset[str]]] = {}
        self._exposure: set[str] = set()
        self._total_bytes = 0
        self._mapping_bytes = 0
        self._depths: dict[str, int] = {}

    def _event(self, kind: str, ids: list[str], parents: list[str] | None = None) -> str:
        return self._emit(kind, ids, parents or []) if self._emit else new_id()

    @property
    def exposed(self) -> tuple[str, ...]:
        return tuple(sorted(self._exposure))

    def get(self, artifact_id: str) -> Artifact:
        try:
            return self._records[artifact_id]
        except KeyError:
            raise ProvenanceError("UNKNOWN_ARTIFACT") from None

    def text(self, artifact_id: str) -> str:
        return self.get(artifact_id).content.decode("utf-8")

    def _check_content(self, text: str) -> bytes:
        if not isinstance(text, str):
            raise ProvenanceError("TEXT_REQUIRED")
        try:
            content = text.encode("utf-8")
        except UnicodeError:
            raise ProvenanceError("INVALID_UNICODE") from None
        if (
            len(content) > MAX_BYTES
            or self._total_bytes + len(content) > MAX_TOTAL_BYTES
            or len(self._records) >= MAX_ARTIFACTS
        ):
            raise ProvenanceError("PROVENANCE_LIMIT")
        return content

    def _check_mapping(self, mapping: dict | None) -> tuple[str | None, int]:
        mapping_json = canonical_json(mapping) if mapping is not None else None
        mapping_size = len(mapping_json.encode("utf-8")) if mapping_json is not None else 0
        if self._mapping_bytes + mapping_size > MAX_MAPPING_BYTES:
            raise ProvenanceError("MAPPING_LIMIT")
        return mapping_json, mapping_size

    def _put(self, content: bytes, envelope: dict, mapping: dict | None = None) -> str:
        document = ProvenanceEnvelope(envelope)
        mapping_json, mapping_size = self._check_mapping(mapping)
        artifact_id = envelope["artifact_id"]
        self._records[artifact_id] = Artifact(content, document)
        self._depths[artifact_id] = 1 + max(
            (self._depths[p] for p in envelope["parents"]), default=0
        )
        self._total_bytes += len(content)
        if mapping_json is not None:
            self._mappings[f"mapping://artifact/{artifact_id}"] = mapping_json
            self._mapping_bytes += mapping_size
        return artifact_id

    def register(
        self,
        text: str,
        *,
        source_id: str,
        profile: ResourceProfile,
        origin_type: str = "DOCUMENT",
        source_event_id: str | None = None,
    ) -> str:
        """Called by trusted ingress; never accepts authority/integrity claims from a model."""
        content = self._check_content(text)
        artifact_id = new_id()
        body = {
            "schema_version": "1.0",
            "artifact_id": artifact_id,
            "content_ref": f"evidence://artifact/{artifact_id}",
            "content_hash": content_hash(content),
            "origin": {"type": origin_type, "source_id": source_id, "event_id": new_id()},
            "authority": "DATA_ONLY",
            "integrity": "UNTRUSTED",
            "confidentiality": profile.confidentiality,
            "allowed_uses": list(profile.allowed_uses),
            "forbidden_uses": list(FORBIDDEN),
            "parents": [],
            "transformations": [],
            "source_spans": [],
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        # Validate before emitting an event that refers to this new Artifact.
        ProvenanceEnvelope(body)
        body["origin"]["event_id"] = self._event(
            "RESOURCE_READ", [artifact_id], [source_event_id] if source_event_id else []
        )
        return self._put(content, body)

    def envelope(self, artifact_id: str) -> ProvenanceEnvelope:
        """Compute current trusted restrictions transitively without changing stored content."""
        cache: dict[str, ProvenanceEnvelope] = {}

        def visit(current: str, path: set[str]) -> ProvenanceEnvelope:
            if current in path or len(path) >= MAX_DEPTH:
                raise ProvenanceError("INVALID_PROVENANCE_DAG")
            if current in cache:
                return cache[current]
            body = self.get(current).envelope.to_dict()
            parents = [visit(p, path | {current}).to_dict() for p in body["parents"]]
            restriction = self._restrictions.get(current, (body["confidentiality"], frozenset()))
            body["confidentiality"] = max(
                [body["confidentiality"], restriction[0]] + [p["confidentiality"] for p in parents],
                key=CONFIDENTIALITY.__getitem__,
            )
            forbidden = set(body["forbidden_uses"]) | set(restriction[1])
            allowed = set(body["allowed_uses"])
            for parent in parents:
                forbidden.update(parent["forbidden_uses"])
                allowed.intersection_update(parent["allowed_uses"])
            body["forbidden_uses"] = sorted(forbidden)
            body["allowed_uses"] = sorted(allowed - forbidden)
            cache[current] = ProvenanceEnvelope(body)
            return cache[current]

        return visit(artifact_id, set())

    def tighten(
        self, artifact_id: str, *, confidentiality: str, forbid_transfer: bool = False
    ) -> None:
        """Trusted classification update; monotone, not an Agent-accessible operation."""
        current = self.envelope(artifact_id).to_dict()
        if (
            confidentiality not in CONFIDENTIALITY
            or CONFIDENTIALITY[confidentiality] < CONFIDENTIALITY[current["confidentiality"]]
        ):
            raise ProvenanceError("CLASSIFICATION_DOWNGRADE")
        previous = self._restrictions.get(artifact_id, (current["confidentiality"], frozenset()))
        forbidden = previous[1] | ({"TRANSFER"} if forbid_transfer else set())
        self._restrictions[artifact_id] = (confidentiality, frozenset(forbidden))

    def ancestors(self, ids: list[str] | tuple[str, ...]) -> set[str]:
        found: set[str] = set()

        def visit(current: str, path: set[str]) -> None:
            if current in path or len(path) >= MAX_DEPTH:
                raise ProvenanceError("INVALID_PROVENANCE_DAG")
            if current in found:
                return
            for parent in self.get(current).envelope.to_dict()["parents"]:
                visit(parent, path | {current})
            found.add(current)

        for artifact_id in ids:
            visit(artifact_id, set())
        return found

    def expose(self, ids: list[str]) -> None:
        for artifact_id in ids:
            assert_use(self.envelope(artifact_id), "READ")
        if len(self._exposure | set(ids)) > MAX_PARENTS:
            raise ProvenanceError("EXPOSURE_LIMIT")
        self._exposure.update(ids)
        self._event("MODEL_EXPOSED", list(self.exposed))

    def _derive(
        self,
        parents: list[str],
        text: str,
        kind: str,
        *,
        mapping: dict | None = None,
        spans: list[dict] | None = None,
        name: str | None = None,
    ) -> str:
        content = self._check_content(text)
        if not parents or len(parents) > MAX_PARENTS or len(set(parents)) != len(parents):
            raise ProvenanceError("INVALID_PARENT_SET")
        self.ancestors(parents)
        if max(self._depths[p] for p in parents) >= MAX_DEPTH:
            raise ProvenanceError("PROVENANCE_DEPTH_LIMIT")
        inputs = [self.envelope(p) for p in parents]
        bodies = [p.to_dict() for p in inputs]
        artifact_id = new_id()
        body = {
            "schema_version": "1.0",
            "artifact_id": artifact_id,
            "content_ref": f"evidence://artifact/{artifact_id}",
            "content_hash": content_hash(content),
            "origin": {
                "type": bodies[0]["origin"]["type"],
                "source_id": name or "trusted-host-derivation",
                "event_id": new_id(),
            },
            "authority": "DATA_ONLY",
            "integrity": "UNTRUSTED",
            "confidentiality": max(
                (p["confidentiality"] for p in bodies), key=CONFIDENTIALITY.__getitem__
            ),
            "allowed_uses": sorted(set.intersection(*(set(p["allowed_uses"]) for p in bodies))),
            "forbidden_uses": sorted(set.union(*(set(p["forbidden_uses"]) for p in bodies))),
            "parents": parents,
            "transformations": [
                {
                    "type": kind,
                    "version": "1",
                    "mapping_ref": f"mapping://artifact/{artifact_id}"
                    if mapping is not None
                    else None,
                }
            ],
            "source_spans": spans or [],
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        child = ProvenanceEnvelope(body)
        assert_ordinary_derivation(inputs, child)
        self._check_mapping(mapping)
        body["origin"]["event_id"] = self._event(
            "CONTENT_SUMMARIZED" if kind in {"SUMMARY", "MODEL_REWRITE"} else "CONTENT_NORMALIZED",
            [artifact_id],
        )
        return self._put(content, body, mapping)

    def copy(self, parent: str, *, name: str = "copy", kind: str = "COPY") -> str:
        if kind not in {"COPY", "SERIALIZE", "SUBAGENT_PASS", "MEMORY_RESTORE"}:
            raise ProvenanceError("UNSUPPORTED_COPY_TRANSFORM")
        text = self.text(parent)
        spans = [span(0, len(text), 0, len(text))]
        return self._derive(
            [parent],
            text,
            kind,
            spans=spans,
            mapping={
                "unit": "unicode-codepoint",
                "kind": kind,
                "segments": [{"parent_id": parent, **spans[0]}],
            },
            name=name,
        )

    def slice(self, parent: str, start: int, end: int) -> str:
        text = self.text(parent)
        if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(text):
            raise ProvenanceError("INVALID_SPAN")
        spans = [span(start, end, 0, end - start)]
        return self._derive(
            [parent],
            text[start:end],
            "SLICE",
            spans=spans,
            mapping={"unit": "unicode-codepoint", "segments": [{"parent_id": parent, **spans[0]}]},
        )

    def decode_base64(self, parent: str) -> str:
        lineage = self.ancestors([parent])
        if (
            sum(
                any(
                    t["type"] == "DECODE" for t in self.get(p).envelope.to_dict()["transformations"]
                )
                for p in lineage
            )
            >= 4
        ):
            raise ProvenanceError("DECODE_DEPTH_LIMIT")
        text = self.text(parent)
        try:
            result = base64.b64decode(text, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeError, ValueError):
            raise ProvenanceError("INVALID_BASE64") from None
        spans = [span(0, len(text), 0, len(result))]
        return self._derive(
            [parent],
            result,
            "DECODE",
            spans=spans,
            mapping={
                "unit": "unicode-codepoint",
                "kind": "BASE64_WHOLE_VALUE",
                "granularity": "whole-value",
                "segments": [{"parent_id": parent, **spans[0]}],
            },
        )

    def concat(self, parents: list[str]) -> str:
        parts, segments, offset = [], [], 0
        for parent in parents:
            text = self.text(parent)
            if parts:
                offset += 1
            parts.append(text)
            segments.append({"parent_id": parent, **span(0, len(text), offset, offset + len(text))})
            offset += len(text)
        return self._derive(
            parents,
            "\n".join(parts),
            "CONCAT",
            mapping={"unit": "unicode-codepoint", "separator": "LF", "segments": segments},
        )

    def rewrite(self, parents: list[str], text: str, *, kind: str = "SUMMARY") -> str:
        if kind not in {"SUMMARY", "MODEL_REWRITE"}:
            raise ProvenanceError("UNSUPPORTED_GENERATION")
        return self._derive(parents, text, kind)

    def generate(self, text: str) -> str:
        if not self.exposed:
            raise ProvenanceError("MISSING_PROVENANCE")
        return self.rewrite(list(self.exposed), text)

    def view(self, parent: str, kind: str = "UNICODE_NFKC_VIEW") -> str:
        original = self.text(parent)
        if kind == "UNICODE_NFKC_VIEW":
            result = unicodedata.normalize("NFKC", original)
            spans = (
                [
                    span(a, b, c, d)
                    for _, a, b, c, d in SequenceMatcher(None, original, result).get_opcodes()
                ]
                if max(len(original), len(result)) <= 4096
                else []
            )
            if not spans or any(
                unicodedata.normalize("NFKC", original[s["source_start"] : s["source_end"]])
                != result[s["view_start"] : s["view_end"]]
                for s in spans
            ):
                spans = [span(0, len(original), 0, len(result))]
        elif kind == "VISIBLE_UNICODE_VIEW":
            parts = [
                f"<U+{ord(c):04X}>" if unicodedata.category(c) in {"Cf", "Cc"} else c
                for c in original
            ]
            result, spans, offset = "".join(parts), [], 0
            if len(parts) <= 4096:
                for index, part in enumerate(parts):
                    spans.append(span(index, index + 1, offset, offset + len(part)))
                    offset += len(part)
            else:
                spans = [span(0, len(original), 0, len(result))]
        else:
            raise ProvenanceError("UNSUPPORTED_VIEW")
        return self._derive(
            [parent],
            result,
            kind,
            spans=spans,
            mapping={
                "unit": "unicode-codepoint",
                "kind": kind,
                "segments": [{"parent_id": parent, **s} for s in spans],
            },
        )

    def mapping(self, reference: str) -> dict:
        try:
            return json.loads(self._mappings[reference])
        except KeyError:
            raise ProvenanceError("UNKNOWN_MAPPING") from None

    def register_mcp(
        self,
        data: dict,
        *,
        source_id: str,
        profile: ResourceProfile,
        source_event_id: str,
        file_parent: str | None = None,
    ) -> list[str]:
        leaves = []

        def walk(value, path: tuple, depth: int) -> None:
            if depth > 12 or len(leaves) > 128:
                raise ProvenanceError("NESTED_RESULT_LIMIT")
            if isinstance(value, str):
                leaves.append((path, value))
            elif isinstance(value, dict):
                for key, child in value.items():
                    walk(child, path + (key,), depth + 1)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, path + (index,), depth + 1)

        walk(data, (), 0)
        if len(leaves) > 128:
            raise ProvenanceError("NESTED_RESULT_LIMIT")
        raw = canonical_json(data)
        root = self.register(
            raw,
            source_id=source_id,
            profile=profile,
            origin_type="MCP_TOOL_RESULT",
            source_event_id=source_event_id,
        )
        if file_parent is not None:
            root = self.rewrite([root, file_parent], raw, kind="MODEL_REWRITE")
        ids = [root]
        for path, text in leaves:
            # Verified JSON extraction; the mapping covers the enclosing value conservatively.
            observed = json.loads(self.text(root))
            for key in path:
                observed = observed[key]
            if observed != text:
                raise ProvenanceError("FIELD_EXTRACTION_MISMATCH")
            spans = [span(0, len(raw), 0, len(text))]
            ids.append(
                self._derive(
                    [root],
                    text,
                    "DECODE",
                    spans=spans,
                    mapping={
                        "unit": "unicode-codepoint",
                        "kind": "JSON_FIELD",
                        "path": list(path),
                        "granularity": "enclosing-value",
                        "segments": [{"parent_id": root, **spans[0]}],
                    },
                )
            )
        self.expose(ids)
        return ids

    def binding_hashes(self, ids: list[str]) -> tuple[str, str]:
        self.ancestors(ids)
        relevant = sorted(self.ancestors(list(set(ids) | self._exposure)))
        return (
            snapshot_hash(
                [
                    {"id": p, "content_hash": self.envelope(p).to_dict()["content_hash"]}
                    for p in sorted(ids)
                ]
            ),
            snapshot_hash(
                {
                    "context": list(self.context),
                    "exposure": list(self.exposed),
                    "envelopes": [self.envelope(p).to_dict() for p in relevant],
                }
            ),
        )

    def redacted_graph(self) -> dict:
        self.ancestors(list(self._records))
        nodes, edges = [], []
        for artifact_id in sorted(self._records):
            body = self.envelope(artifact_id).to_dict()
            nodes.append(
                {
                    "id": artifact_id,
                    "kind": "artifact",
                    "authority": body["authority"],
                    "integrity": body["integrity"],
                    "confidentiality": body["confidentiality"],
                    "allowed_uses": body["allowed_uses"],
                    "forbidden_uses": body["forbidden_uses"],
                    "transformations": [t["type"] for t in body["transformations"]],
                    "origin_type": body["origin"]["type"],
                    "origin_event_id": body["origin"]["event_id"],
                }
            )
            edges.extend(
                {
                    "source": parent,
                    "target": artifact_id,
                    "type": "DERIVED_FROM",
                    "certainty": "conservative"
                    if any(
                        t["type"] in {"SUMMARY", "MODEL_REWRITE"} for t in body["transformations"]
                    )
                    else "observed",
                }
                for parent in body["parents"]
            )
        subject = f"subject:{self.context[2]}"
        nodes.append({"id": subject, "kind": "subject"})
        edges.extend(
            {"source": p, "target": subject, "type": "EXPOSED_TO", "certainty": "observed"}
            for p in self.exposed
        )
        return {"nodes": nodes, "edges": edges}
