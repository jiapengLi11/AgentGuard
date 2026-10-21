"""Typed cross-MCP / multi-agent provenance graph built from the M1 trace ledger.

The graph is an offline, read-only projection: it never changes a decision and
never feeds back into authorization. It joins

* the append-only ``TraceLedger`` (events, payloads, artifact envelopes, raw
  artifact bodies kept in the trusted evidence store), and
* an optional ``ProvenanceRecorder`` that observes ``M1Gateway.call`` and
  ``spawn_child`` to keep the readable call arguments, which the ledger itself
  stores only as hashes.

Every argument, result preview and payload excerpt that leaves this module is
passed through :func:`redact` first: private keys, API tokens, credential
fields and any substring of a ``SECRET`` artifact are masked, and a hash of
the original value is kept so the evidence stays verifiable.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from . import detection_v2 as _rules
from .contracts import canonical_json
from .contracts import snapshot_hash as sha
from .zh_rules import ZH_RULES

GRAPH_SCHEMA = "sujie-provenance-graph-v1"
TOKENIZER = "sujie-simple-v1"  # word runs, single CJK chars, single punctuation marks
ULID = re.compile(r"\b[0-9A-HJKMNP-TV-Z]{26}\b")

NODE_TYPES = (
    "source",  # trigger source: user message / external resource / memory
    "content",  # an artifact (content-addressed evidence) in the trace ledger
    "span",  # the exact payload span inside a content node (char/byte/token offsets)
    "agent",  # main agent or sub-agent (with parent and depth)
    "gateway",  # the policy enforcement point + StdioMCPProxy
    "mcp_server",  # an MCP server reached through the proxy (or the trusted host)
    "tool_call",  # one proposed tool call with readable redacted params and result
    "decision",  # ALLOW / ASK / BLOCK with rule, risk and explanation
    "impact",  # effect target: local file, credential store, network, git repo, memory
)
EDGE_TYPES = (
    "ORIGIN_OF",  # source -> content
    "TASKS",  # user source -> main agent
    "CONTAINS",  # content -> span
    "DERIVES",  # parent content -> derived content
    "INFLUENCES",  # tainted span/content in the agent context -> tool call
    "FLOWS_INTO",  # content whose bytes appear in the call arguments -> tool call
    "PROPOSES",  # agent -> tool call
    "SPAWNS",  # delegation tool call -> child agent
    "DECIDED_BY",  # tool call -> decision
    "EVALUATES",  # gateway -> decision
    "ROUTED_TO",  # tool call -> MCP server (executed=false when blocked before the proxy)
    "RETURNS",  # tool call -> result content
    "ALLOWED_EFFECT",  # decision -> impact (executed)
    "PENDING_EFFECT",  # decision -> impact (ASK, not executed)
    "PREVENTED_EFFECT",  # decision -> impact (blocked)
)

# ---------------------------------------------------------------------------
# Redaction


_PEM = re.compile(r"-----BEGIN ([A-Z0-9 ]*PRIVATE KEY)-----.*?(?:-----END \1-----|\Z)", re.S)
_TOKEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
    re.compile(r"\bssh-(?:rsa|ed25519|dss) AAAA[A-Za-z0-9+/=]{20,}"),
)
_SECRET_FIELD = re.compile(
    r"(?:pass(?:word|wd)?|secret|token|api[_-]?key|authorization|cookie|private[_-]?key"
    r"|credential|session)",
    re.I,
)
_LONG_BLOB = re.compile(r"[A-Za-z0-9+/_=-]{48,}")
MAX_TEXT = 160


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _mask(value: str, kind: str) -> str:
    return f"[REDACTED:{kind} {len(value)} chars {_digest(value)}]"


def secret_fingerprints(secrets: list[str]) -> list[str]:
    """Substrings of known SECRET bodies that must never be shown verbatim."""
    prints: set[str] = set()
    for secret in secrets:
        text = secret.strip()
        if 8 <= len(text) <= 8192:
            prints.add(text)
        for line in secret.splitlines():
            line = line.strip()
            if len(line) >= 12 and not line.startswith("-----"):
                prints.add(line)
    return sorted(prints, key=len, reverse=True)


def redact_text(text: str, fingerprints: list[str] | None = None, *, limit: int = MAX_TEXT) -> str:
    out = _PEM.sub(lambda m: _mask(m.group(0), "private-key"), text)
    for print_ in fingerprints or ():
        if print_ in out:
            out = out.replace(print_, _mask(print_, "secret-artifact"))
        encoded = unquote(out)
        if encoded != out and print_ in encoded:
            out = encoded.replace(print_, _mask(print_, "secret-artifact"))
    for pattern in _TOKEN_PATTERNS:
        out = pattern.sub(lambda m: _mask(m.group(0), "token"), out)
    out = _LONG_BLOB.sub(
        lambda m: m.group(0) if m.group(0).startswith("sha256") else _mask(m.group(0), "blob"),
        out,
    )
    if limit and len(out) > limit:
        out = out[:limit] + f"…(+{len(out) - limit} chars)"
    return out


def _redact_url(url: str, fingerprints: list[str]) -> str:
    try:
        parts = urlsplit(url)
        query = parse_qsl(parts.query, keep_blank_values=True)
    except ValueError:
        return redact_text(url, fingerprints)
    if not query:
        return redact_text(url, fingerprints)
    cleaned = []
    for name, value in query:
        masked = redact_text(value, fingerprints, limit=0)
        if masked == value and (_SECRET_FIELD.search(name) or len(value) > 40):
            masked = _mask(value, "query-value")
        cleaned.append((name, masked))
    rebuilt = urlunsplit(parts._replace(query=urlencode(cleaned, safe="[]:. ", quote_via=quote)))
    return redact_text(rebuilt, fingerprints, limit=240)


def redact(value: Any, fingerprints: list[str] | None = None, *, key: str = "") -> Any:
    """Readable-but-safe copy of a JSON value (dict keys preserved, order sorted)."""
    prints = fingerprints or []
    if isinstance(value, dict):
        return {k: redact(value[k], prints, key=str(k)) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [redact(item, prints, key=key) for item in value[:32]]
    if isinstance(value, str):
        if key and _SECRET_FIELD.search(key) and value:
            return _mask(value, "field")
        if re.match(r"https?://", value):
            return _redact_url(value, prints)
        return redact_text(value, prints)
    return value


# ---------------------------------------------------------------------------
# Token-level payload location


_SENTENCE_END = re.compile(r"[.!?](?=\s|$)|[。！？\n]|-->|<!--")
_TOKEN = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff\uf900-\ufaff]|[^\sA-Za-z0-9_]")


def tokenize(text: str) -> list[tuple[int, int]]:
    """Deterministic tokenizer (``TOKENIZER``); returns raw char offsets per token."""
    return [(m.start(), m.end()) for m in _TOKEN.finditer(text)]


def _mapped_view(raw: str) -> tuple[str, list[int]]:
    """Per-char NFKC + Cf removal + lookalike folding, with a view->raw offset map."""
    pieces: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(raw):
        if unicodedata.category(char) == "Cf":
            continue
        normalized = unicodedata.normalize("NFKC", char).translate(_rules.LOOKALIKES)
        pieces.append(normalized)
        origin.extend([index] * len(normalized))
    return "".join(pieces), origin


def _payload_patterns() -> list[tuple[str, re.Pattern]]:
    patterns: list[tuple[str, re.Pattern]] = []
    for item in (*_rules.OVERRIDE_PATTERNS, *_rules.EXTRA_OVERRIDE_PATTERNS):
        patterns.append(("untrusted_text_requests_instruction_override", item))
    patterns += [
        ("untrusted_text_directs_agent_action", _rules.AGENT_DIRECTIVE),
        ("untrusted_text_directs_agent_action", _rules.CONCEALMENT_DIRECTIVE),
        ("untrusted_text_directs_agent_action", _rules.PARAMETER_REWRITE),
        ("untrusted_text_claims_authority", _rules.FORGED_AUTHORITY),
        ("untrusted_text_requests_sensitive_effect", _rules.SENSITIVE_EFFECT),
    ]
    patterns += [(reason, pattern) for _, reason, pattern in _rules.V5_RULES]
    patterns += [(reason, pattern) for _, reason, pattern in ZH_RULES]
    return patterns


_PATTERNS = _payload_patterns()


def locate_payload_spans(raw: str) -> list[dict[str, Any]]:
    """Exact raw-source spans of instruction-like payload text.

    Matches are computed on a normalized view (NFKC, zero-width removal,
    homoglyph folding) and mapped back to the untouched source, so offsets
    always index the stored artifact body. Encoded payloads that only appear
    after decoding cannot be mapped and yield no span (callers fall back to the
    whole artifact, flagged ``precision="artifact"``).
    """
    if not raw:
        return []
    view, origin = _mapped_view(raw[: _rules.MAX_SCAN_CHARS])
    hits: list[tuple[int, int, str]] = []
    for reason, pattern in _PATTERNS:
        for match in pattern.finditer(view):
            if match.end() > match.start():
                hits.append((origin[match.start()], origin[match.end() - 1] + 1, reason))
    if not hits:
        return []
    hits.sort()
    merged: list[list[Any]] = []
    for start, end, reason in hits:
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
            if reason not in merged[-1][2]:
                merged[-1][2].append(reason)
        else:
            merged.append([start, end, [reason]])
    tokens = tokenize(raw)
    spans = []
    for start, end, reasons in merged:
        # Extend to the enclosing sentence so the span is a readable instruction.
        bounds = [m.end() for m in _SENTENCE_END.finditer(raw)]
        left = max((b for b in bounds if b <= start), default=0)
        right = min((b for b in bounds if b >= end), default=len(raw))
        while left < start and raw[left].isspace():
            left += 1
        overlapping = [i for i, (a, b) in enumerate(tokens) if a < right and b > left]
        spans.append(
            {
                "char_start": left,
                "char_end": right,
                "byte_start": len(raw[:left].encode("utf-8")),
                "byte_end": len(raw[:right].encode("utf-8")),
                "token_start": overlapping[0] if overlapping else 0,
                "token_end": overlapping[-1] + 1 if overlapping else 0,
                "match_char_start": start,
                "match_char_end": end,
                "reasons": sorted(reasons),
                "tokenizer": TOKENIZER,
            }
        )
    # Sentence extension can make neighbours overlap; merge again.
    final: list[dict[str, Any]] = []
    for span in spans:
        if final and span["char_start"] < final[-1]["char_end"]:
            last = final[-1]
            last["char_end"] = max(last["char_end"], span["char_end"])
            last["byte_end"] = max(last["byte_end"], span["byte_end"])
            last["token_end"] = max(last["token_end"], span["token_end"])
            last["match_char_end"] = max(last["match_char_end"], span["match_char_end"])
            last["reasons"] = sorted(set(last["reasons"]) | set(span["reasons"]))
        else:
            final.append(span)
    return final


# ---------------------------------------------------------------------------
# Recorder (observes the live gateway; never changes its behaviour)


class ProvenanceRecorder:
    """Keeps readable call arguments and the agent tree for one gateway family.

    It wraps ``call`` and ``spawn_child`` on the given gateway instances only.
    Bookkeeping failures are swallowed so observation can never break a run.
    Raw arguments stay in memory; exports only ever see :func:`redact` output.
    """

    def __init__(self, gateway: Any, *, label: str = "main-agent") -> None:
        self.trace = gateway.trace
        self.agents: dict[str, dict[str, Any]] = {}
        self.calls: dict[str, dict[str, Any]] = {}
        self.servers: dict[str, dict[str, Any]] = {}
        self._pending_labels: list[str] = []
        self._capture_servers(gateway)
        self.attach(gateway, label=label, parent=None)

    def _capture_servers(self, gateway: Any) -> None:
        try:
            for name, spec in sorted(gateway.proxy.registry.items()):
                alias = name.split(".", 1)[0]
                entry = self.servers.setdefault(
                    alias,
                    {
                        "server_name": spec.server_name,
                        "server_version": spec.server_version,
                        "tools": [],
                    },
                )
                entry["tools"].append(spec.tool_name)
        except Exception:  # pragma: no cover - observation only
            pass

    def label_next_child(self, label: str) -> None:
        """Name the next agent spawned through any observed gateway."""
        self._pending_labels.append(label)

    def attach(self, gateway: Any, *, label: str, parent: str | None) -> None:
        grant = gateway.grant.to_dict()
        depth = 0 if parent is None else self.agents[parent]["depth"] + 1
        self.agents[grant["subject_id"]] = {
            "label": label,
            "role": "main" if parent is None else "sub",
            "depth": depth,
            "parent": parent,
            "grant_id": grant["grant_id"],
            "effects": sorted(grant["effects"]),
            "resource_scopes": list(grant["resource_scopes"]),
            "budgets": dict(sorted(grant.get("budgets", {}).items())),
        }
        original_call = gateway.call
        original_spawn = gateway.spawn_child
        recorder = self

        async def call(tool, args, **kwargs):
            start = len(recorder.trace.events)
            result = await original_call(tool, args, **kwargs)
            try:
                recorder._remember(start, grant["subject_id"], tool, args, result)
            except Exception:  # pragma: no cover - observation only
                pass
            return result

        async def spawn_child(child_grant, **kwargs):
            result, child = await original_spawn(child_grant, **kwargs)
            if child is not None:
                try:
                    name = (
                        recorder._pending_labels.pop(0)
                        if recorder._pending_labels
                        else f"sub-agent-{len(recorder.agents)}"
                    )
                    recorder.attach(child, label=name, parent=grant["subject_id"])
                except Exception:  # pragma: no cover - observation only
                    pass
            return result, child

        gateway.call = call
        gateway.spawn_child = spawn_child

    def _remember(self, start: int, actor: str, tool: str, args: dict, result: dict) -> None:
        wanted = sha(args)
        for event in self.trace.events[start:]:
            payload = self.trace.payloads[event["event_id"]]
            if (
                event["event_type"] == "TOOL_PROPOSED"
                and event["event_id"] not in self.calls
                and payload.get("tool") == tool
                and payload.get("arguments_hash") == wanted
            ):
                self.calls[event["event_id"]] = {
                    "arguments": json.loads(canonical_json(args)),
                    "outcome": {
                        key: result.get(key) for key in ("ok", "decision", "code") if key in result
                    },
                }
                return


# ---------------------------------------------------------------------------
# Graph model


@dataclass
class Node:
    id: str
    type: str
    label: str
    attrs: dict[str, Any] = field(default_factory=dict)
    seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "seq": self.seq,
            "attrs": self.attrs,
        }


@dataclass
class Edge:
    src: str
    dst: str
    type: str
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"src": self.src, "dst": self.dst, "type": self.type, "attrs": self.attrs}


@dataclass
class ProvenanceGraph:
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    lanes: list[dict[str, str]] = field(default_factory=list)
    focus: str | None = None
    attack_path: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def add(self, node: Node) -> Node:
        if node.type not in NODE_TYPES:
            raise ValueError("UNKNOWN_NODE_TYPE")
        self.nodes.setdefault(node.id, node)
        return self.nodes[node.id]

    def link(self, src: str, dst: str, edge_type: str, **attrs: Any) -> None:
        if edge_type not in EDGE_TYPES or src not in self.nodes or dst not in self.nodes:
            raise ValueError("INVALID_EDGE")
        if any(e.src == src and e.dst == dst and e.type == edge_type for e in self.edges):
            return
        self.edges.append(Edge(src, dst, edge_type, attrs))

    def of_type(self, kind: str) -> list[Node]:
        return [node for node in self.nodes.values() if node.type == kind]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GRAPH_SCHEMA,
            "focus": self.focus,
            "attack_path": self.attack_path,
            "summary": self.summary,
            "lanes": self.lanes,
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
            "timeline": self.timeline,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# Builder


SEVERITY = {
    "data.transfer": 3,
    "external.data_transfer": 3,
    "exec": 3,
    "git.push": 3,
    "credential.read": 2,
    "agent.delegate": 2,
    "file.write": 2,
    "memory.write": 2,
    "file.read": 1,
    "memory.read": 1,
}
_CREDENTIAL_PATH = re.compile(
    r"(?:/\.ssh(?:/|$)|/\.aws/|/\.gnupg/|/\.docker/config|/\.kube/|/\.netrc|(?:^|/)\.env\b"
    r"|id_(?:rsa|ed25519|ecdsa|dsa)\b|credentials?|secret|keychain|token)",
    re.I,
)


def impact_category(kind: str, resource: str) -> str:
    if resource.startswith(("http://", "https://")):
        return "network"
    if kind == "credential.read" or _CREDENTIAL_PATH.search(resource):
        return "credential_store"
    if kind == "git.push" or ".git/" in resource or resource.endswith(".git"):
        return "git_repo"
    if kind.startswith("memory."):
        return "memory"
    if kind == "agent.delegate":
        return "agent"
    return "local_file"


def _source_kind(origin_type: str) -> str | None:
    return {
        "USER_MESSAGE": "user",
        "MCP_TOOL_RESULT": "external",
        "WEB_PAGE": "external",
        "MEMORY": "memory",
    }.get(origin_type)


def _rule_of(reason: str) -> str:
    return reason if reason.islower() else f"precondition:{reason}"


def _assess_risk(
    effect: dict | None,
    tainted: list[str],
    secret_inputs: list[str],
    secret_flows: list[str],
    findings: list[str],
) -> dict[str, Any]:
    """Independent provenance risk; it explains, it never authorizes."""
    factors = []
    score = 0
    if effect:
        severity = SEVERITY.get(effect["kind"], 1)
        score += severity
        factors.append(f"effect {effect['kind']} (severity {severity})")
        if effect.get("destination_trust") == "UNTRUSTED_EXTERNAL":
            score += 2
            factors.append("destination is UNTRUSTED_EXTERNAL")
        if effect.get("side_effect"):
            score += 1
            factors.append(
                "irreversible side effect" if not effect.get("reversible") else "side effect"
            )
    if tainted:
        score += 2
        factors.append(f"context carries {len(tainted)} injection-flagged source(s)")
    if secret_inputs:
        score += 1
        factors.append(f"context holds {len(secret_inputs)} SECRET source(s)")
    if secret_flows:
        score += 3
        factors.append("SECRET bytes appear in the call arguments")
    if findings:
        factors.append("findings: " + ", ".join(sorted(set(findings))))
    level = (
        "CRITICAL" if score >= 9 else "HIGH" if score >= 6 else "MEDIUM" if score >= 3 else "LOW"
    )
    return {"level": level, "score": score, "factors": factors}


def _explain(
    decision: str, reason: str, alignment: dict | None, effect: dict | None, risk: dict
) -> str:
    if decision == "ALLOW":
        return "Allowed: inside contract, grant and DSL rule " + reason + "."
    parts = [f"{decision} by {_rule_of(reason)}"]
    if alignment and alignment.get("deviation"):
        facts = "; ".join(f"{f['field']}={f['summary']}" for f in alignment.get("facts", [])[:3])
        parts.append(f"deviation {alignment['deviation']}: {facts}")
    if effect:
        parts.append(f"attempted {effect['kind']} -> {', '.join(effect['resources'])}")
    parts.append(f"provenance risk {risk['level']}")
    return ". ".join(parts) + "."


def _flows(content: str, arguments: Any) -> bool:
    serialized = canonical_json(arguments)
    decoded = unquote(unquote(serialized))
    for candidate in secret_fingerprints([content]):
        if len(candidate) >= 12 and (candidate in serialized or candidate in decoded):
            return True
    return False


def build_provenance_graph(
    trace: Any,
    recorder: ProvenanceRecorder | None = None,
    *,
    focus_decision_seq: int | None = None,
    collapse_structured: bool = True,
    previews: bool = True,
) -> ProvenanceGraph:
    """Project a trace into the typed graph.

    ``previews=False`` keeps offsets and hashes but omits every content preview and
    payload excerpt (operator console policy: views never serialize artifact text).
    """
    graph = ProvenanceGraph()
    events = sorted(trace.events, key=lambda e: e["sequence"])
    payloads = trace.payloads
    by_id = {e["event_id"]: e for e in events}
    envelopes = {aid: env.to_dict() for aid, env in trace.artifacts.items()}
    contents = trace.artifact_contents
    secrets = [contents[a] for a, env in envelopes.items() if env["confidentiality"] == "SECRET"]
    prints = secret_fingerprints(secrets)
    principal = trace._contract["principal_id"]
    server_actors = {e["actor_id"] for e in events if e["event_type"] == "TOOL_REGISTERED"}

    # -- MCP servers + gateway ------------------------------------------------
    gateway = graph.add(
        Node("gw", "gateway", "M1 Gateway + StdioMCPProxy", {"role": "policy enforcement point"})
    )
    registered: dict[str, dict[str, Any]] = {}
    for event in events:
        if event["event_type"] == "TOOL_REGISTERED":
            name = payloads[event["event_id"]]["qualified_name"]
            alias, tool = name.split(".", 1)
            registered.setdefault(alias, {"tools": []})["tools"].append(tool)
    if recorder is not None:
        for alias, info in recorder.servers.items():
            registered.setdefault(alias, {"tools": list(info["tools"])}).update(
                server_name=info["server_name"], server_version=info["server_version"][:24]
            )

    def mcp_node(alias: str) -> str:
        node_id = f"mcp:{alias}"
        if node_id not in graph.nodes:
            info = registered.get(alias, {"tools": []})
            label = "trusted host (delegation)" if alias == "host" else f"MCP {alias}"
            graph.add(
                Node(
                    node_id,
                    "mcp_server",
                    label,
                    {
                        "alias": alias,
                        "server_name": info.get(
                            "server_name", "trusted-host" if alias == "host" else alias
                        ),
                        "tools": sorted(set(info.get("tools", []))),
                    },
                )
            )
        return node_id

    for alias in sorted(registered):
        mcp_node(alias)

    # -- agents ---------------------------------------------------------------
    delegations: dict[str, tuple[str, str]] = {}  # exec event id -> (parent actor, child grant)
    for event in events:
        payload = payloads[event["event_id"]]
        if (
            event["event_type"] == "EXECUTION_RESULT"
            and payload.get("tool") == "host.delegate"
            and payload.get("ok")
        ):
            delegations[event["event_id"]] = (event["actor_id"], payload.get("child_grant_id"))
    actors: list[str] = []
    for event in events:
        actor = event["actor_id"]
        if actor in server_actors or actor == principal or actor in actors:
            continue
        if event["event_type"] in {
            "TOOL_PROPOSED",
            "MODEL_EXPOSED",
            "CONTENT_SUMMARIZED",
            "RESOURCE_READ",
            "CONTENT_REGISTERED",
            "DETECTION_FINDING",
            "TOOL_CALL_DECIDED",
            "EXECUTION_RESULT",
        }:
            actors.append(actor)
    parent_of: dict[str, str | None] = {}
    child_exec: dict[str, str] = {}
    for actor in actors:
        parents = {p for e in events if e["actor_id"] == actor for p in e["parent_event_ids"]}
        hit = sorted(parents & set(delegations), key=lambda x: by_id[x]["sequence"])
        parent_of[actor] = delegations[hit[0]][0] if hit else None
        if hit:
            child_exec[actor] = hit[0]
    known = recorder.agents if recorder is not None else {}
    for actor, info in known.items():
        if actor not in actors:
            actors.append(actor)
        parent_of[actor] = info["parent"]
    agent_ids: dict[str, str] = {}

    def depth(actor: str) -> int:
        level, cursor = 0, parent_of.get(actor)
        while cursor is not None:
            level, cursor = level + 1, parent_of.get(cursor)
        return level

    for index, actor in enumerate(sorted(actors, key=lambda a: (depth(a), actors.index(a)))):
        info = known.get(actor, {})
        role = "main" if parent_of.get(actor) is None else "sub"
        label = info.get("label") or ("main-agent" if role == "main" else f"sub-agent-{index}")
        node_id = f"agent:{index}"
        agent_ids[actor] = node_id
        graph.add(
            Node(
                node_id,
                "agent",
                label,
                {
                    "role": role,
                    "depth": depth(actor),
                    "parent": None,
                    "effects": info.get("effects"),
                    "resource_scopes": info.get("resource_scopes"),
                    "budgets": info.get("budgets"),
                },
            )
        )
    for actor, node_id in agent_ids.items():
        parent = parent_of.get(actor)
        graph.nodes[node_id].attrs["parent"] = agent_ids.get(parent) if parent else None

    # -- content, sources, spans --------------------------------------------
    order = list(envelopes)
    collapsed: dict[str, str] = {}
    for aid in order:
        env = envelopes[aid]
        if (
            collapse_structured
            and env["origin"]["source_id"].endswith(":structured-result")
            and env["parents"]
            and envelopes[env["parents"][0]]["origin"]["event_id"] == env["origin"]["event_id"]
        ):
            collapsed[aid] = env["parents"][0]
    content_ids: dict[str, str] = {}
    findings_by_artifact: dict[str, list[dict]] = {}
    document_sources: dict[str, dict] = {}
    for event in events:
        payload = payloads[event["event_id"]]
        if event["event_type"] == "CONTENT_REGISTERED" and "document_source" in payload:
            for aid in event["artifact_ids"]:
                document_sources[aid] = payload["document_source"]
        if event["event_type"] == "DETECTION_FINDING":
            finding = payloads[event["event_id"]]["finding"]
            for aid in event["artifact_ids"]:
                target = collapsed.get(aid, aid)
                findings_by_artifact.setdefault(target, []).append(
                    {
                        "seq": event["sequence"],
                        **{
                            k: finding[k]
                            for k in (
                                "attack_source",
                                "attack_family",
                                "reasons",
                                "detector_version",
                                "confidence",
                            )
                        },
                    }
                )
    span_nodes: dict[str, list[str]] = {}
    for index, aid in enumerate(order):
        if aid in collapsed:
            continue
        env = envelopes[aid]
        body = contents.get(aid, "")
        origin_event = by_id.get(env["origin"]["event_id"])
        node_id = f"content:{index}"
        content_ids[aid] = node_id
        preview_source = body if env["confidentiality"] != "SECRET" and previews else ""
        graph.add(
            Node(
                node_id,
                "content",
                env["origin"]["source_id"][:80],
                {
                    "origin_type": env["origin"]["type"],
                    "source_id": env["origin"]["source_id"],
                    "authority": env["authority"],
                    "integrity": env["integrity"],
                    "confidentiality": env["confidentiality"],
                    "forbidden_uses": env["forbidden_uses"],
                    "content_hash": env["content_hash"],
                    "chars": len(body),
                    "preview": redact_text(preview_source, prints, limit=120)
                    if preview_source
                    else _mask(body, "secret-artifact" if previews else "hidden")
                    if body
                    else "",
                    "findings": findings_by_artifact.get(aid, []),
                    "structured_twin": sorted(k for k, v in collapsed.items() if v == aid),
                },
                seq=origin_event["sequence"] if origin_event else 0,
            )
        )
        kind = _source_kind(env["origin"]["type"])
        # A trigger source is user/memory input, or external content that carries a finding.
        if kind == "external" and not findings_by_artifact.get(aid) and aid not in document_sources:
            kind = None
        if kind and (not env["parents"] or aid in document_sources):
            src_id = f"source:{index}"
            resource = env["origin"]["source_id"]
            label = {
                "user": "user message",
                "external": "external resource " + resource.split(":", 1)[-1],
                "memory": "memory " + resource.split(":", 1)[-1],
            }[kind]
            graph.add(
                Node(
                    src_id,
                    "source",
                    label,
                    {
                        "kind": kind,
                        "origin_type": env["origin"]["type"],
                        "locator": resource,
                        "trust": "USER_REQUEST" if kind == "user" else "UNTRUSTED",
                        **document_sources.get(aid, {}),
                    },
                    seq=graph.nodes[node_id].seq,
                )
            )
            graph.link(src_id, node_id, "ORIGIN_OF")
        if findings_by_artifact.get(aid) and env["confidentiality"] != "SECRET":
            spans = locate_payload_spans(body)
            if not spans:
                spans = [
                    {
                        "char_start": 0,
                        "char_end": len(body),
                        "byte_start": 0,
                        "byte_end": len(body.encode("utf-8")),
                        "token_start": 0,
                        "token_end": len(tokenize(body)),
                        "match_char_start": 0,
                        "match_char_end": len(body),
                        "reasons": sorted(
                            {r for f in findings_by_artifact[aid] for r in f["reasons"]}
                        ),
                        "tokenizer": TOKENIZER,
                        "precision": "artifact",
                    }
                ]
            for k, span in enumerate(spans):
                span_id = f"span:{index}.{k}"
                excerpt = body[span["char_start"] : span["char_end"]]
                graph.add(
                    Node(
                        span_id,
                        "span",
                        f"payload chars {span['char_start']}-{span['char_end']}",
                        {
                            **span,
                            "precision": span.get("precision", "token"),
                            "excerpt": redact_text(excerpt, prints, limit=200)
                            if previews
                            else _mask(excerpt, "hidden"),
                            "excerpt_hash": sha(excerpt),
                        },
                        seq=graph.nodes[node_id].seq,
                    )
                )
                graph.link(node_id, span_id, "CONTAINS")
                span_nodes.setdefault(aid, []).append(span_id)
    for aid in order:
        if aid in collapsed:
            continue
        for parent in envelopes[aid]["parents"]:
            parent = collapsed.get(parent, parent)
            if parent in content_ids and parent != aid:
                graph.link(content_ids[parent], content_ids[aid], "DERIVES")

    goal = trace._contract.get("trusted_goal")
    if goal:
        graph.add(
            Node(
                "source:goal",
                "source",
                "user request (TaskContract goal)",
                {
                    "kind": "user",
                    "origin_type": "TASK_CONTRACT",
                    "locator": "contract.trusted_goal",
                    "trust": "USER_REQUEST",
                    "preview": redact_text(goal, prints, limit=160),
                },
                seq=-1,
            )
        )
    users = [n for n in graph.of_type("source") if n.attrs["kind"] == "user"]
    mains = [agent_ids[a] for a in agent_ids if parent_of.get(a) is None]
    for user in users:
        for main in mains:
            graph.link(user.id, main, "TASKS")

    # -- tool calls, decisions, impacts ---------------------------------------
    children: dict[str, list[dict]] = {}
    for event in events:
        for parent in event["parent_event_ids"]:
            children.setdefault(parent, []).append(event)
    exec_by_decision = {
        e["decision_id"]: e
        for e in events
        if e["event_type"] == "EXECUTION_RESULT" and e.get("decision_id")
    }
    calls_by_seq: dict[int, str] = {}
    for event in events:
        if event["event_type"] != "TOOL_PROPOSED" or event["actor_id"] not in agent_ids:
            continue
        payload = payloads[event["event_id"]]
        tool = payload["tool"]
        seq = event["sequence"]
        agent_node = agent_ids[event["actor_id"]]
        decided = next(
            (
                c
                for c in children.get(event["event_id"], [])
                if c["event_type"] == "TOOL_CALL_DECIDED"
            ),
            None,
        )
        dpayload = payloads[decided["event_id"]] if decided else {}
        executed = None
        if decided is not None:
            executed = next(
                (
                    c
                    for c in children.get(decided["event_id"], [])
                    if c["event_type"] == "EXECUTION_RESULT"
                ),
                None,
            )
            if executed is None and decided.get("decision_id"):
                executed = exec_by_decision.get(decided["decision_id"])
        effect = (dpayload.get("semantic_action") or {}).get("effect")
        captured = recorder.calls.get(event["event_id"]) if recorder is not None else None
        exposed = [collapsed.get(a, a) for a in event["artifact_ids"]]
        exposed = list(dict.fromkeys(a for a in exposed if a in content_ids))
        tainted = [a for a in exposed if findings_by_artifact.get(a)]
        secret_inputs = [a for a in exposed if envelopes[a]["confidentiality"] == "SECRET"]
        secret_flows = (
            [a for a in secret_inputs if _flows(contents.get(a, ""), captured["arguments"])]
            if captured
            else []
        )
        result_artifacts = []
        if executed is not None:
            result_artifacts = [
                content_ids[a]
                for a in order
                if a in content_ids and envelopes[a]["origin"]["event_id"] == executed["event_id"]
            ]
        exec_payload = payloads[executed["event_id"]] if executed else {}
        result_preview = ""
        if result_artifacts:
            first = graph.nodes[result_artifacts[0]]
            result_preview = first.attrs["preview"]
        call_id = f"call:{seq}"
        calls_by_seq[seq] = call_id
        params = (
            redact(captured["arguments"], prints)
            if captured
            else {"normalized_effect": effect}
            if effect
            else {}
        )
        if tool == "host.delegate":
            params = {
                "child_grant": "narrowed child grant",
                "input_artifacts": len(event["artifact_ids"]),
                "analysis_only": payload.get("analysis_only", False),
            }
        graph.add(
            Node(
                call_id,
                "tool_call",
                tool,
                {
                    "tool": tool,
                    "mcp_server": tool.split(".", 1)[0],
                    "agent": agent_node,
                    "params": params,
                    "params_source": "recorder (redacted)"
                    if captured
                    else "ledger (hash + normalized effect)",
                    "arguments_hash": None
                    if tool == "host.delegate"
                    else payload.get("arguments_hash"),
                    "input_artifacts": [content_ids[a] for a in exposed],
                    "executed": bool(executed and exec_payload.get("ok")),
                    "result": {
                        "ok": exec_payload.get("ok") if executed else False,
                        "code": exec_payload.get("code")
                        or (dpayload.get("reason") if not executed else None),
                        "artifacts": result_artifacts,
                        "preview": result_preview,
                    },
                    "trusted_probe": payload.get("kind") == "TRUSTED_HOST_STATE_CHECK",
                },
                seq=seq,
            )
        )
        graph.link(agent_node, call_id, "PROPOSES")
        for aid in tainted:
            for target in span_nodes.get(aid, [content_ids[aid]]):
                graph.link(target, call_id, "INFLUENCES", reason="injection finding in context")
        for aid in secret_flows:
            graph.link(content_ids[aid], call_id, "FLOWS_INTO", secret=True)
        server = mcp_node(tool.split(".", 1)[0])
        graph.link(call_id, server, "ROUTED_TO", executed=bool(executed and exec_payload.get("ok")))
        for result_id in result_artifacts:
            graph.link(call_id, result_id, "RETURNS")
        if decided is None:
            continue
        decision = dpayload.get("decision", "BLOCK")
        reason = dpayload.get("reason", "UNKNOWN")
        risk = _assess_risk(
            effect,
            [content_ids[a] for a in tainted],
            [content_ids[a] for a in secret_inputs],
            [content_ids[a] for a in secret_flows],
            [f["attack_family"] for a in tainted for f in findings_by_artifact[a]],
        )
        record = dpayload.get("record") or {}
        alignment = dpayload.get("alignment")
        if alignment:
            # Artifact ULIDs in facts become graph node ids (readable and run-independent).
            alignment = json.loads(
                ULID.sub(
                    lambda m: content_ids.get(collapsed.get(m.group(0), m.group(0)), m.group(0)),
                    json.dumps(alignment),
                )
            )
        dec_id = f"decision:{decided['sequence']}"
        graph.add(
            Node(
                dec_id,
                "decision",
                f"{decision} {reason}",
                {
                    "decision": decision,
                    "reason": reason,
                    "rule": _rule_of(reason),
                    "hard_block": record.get(
                        "hard_block", decision == "BLOCK" and reason.isupper()
                    ),
                    "runtime_risk": record.get("risk"),
                    "provenance_risk": risk,
                    "alignment": alignment,
                    "explanation": _explain(decision, reason, alignment, effect, risk),
                    "effect": effect,
                },
                seq=decided["sequence"],
            )
        )
        graph.nodes[call_id].attrs["decision_node"] = dec_id
        graph.link(call_id, dec_id, "DECIDED_BY")
        graph.link(gateway.id, dec_id, "EVALUATES")
        if tool == "host.delegate" and executed is not None:
            for actor, exec_id in child_exec.items():
                if exec_id == executed["event_id"]:
                    graph.link(call_id, agent_ids[actor], "SPAWNS")
            if recorder is not None:
                for actor, info in recorder.agents.items():
                    if info["parent"] == event["actor_id"] and info["grant_id"] == exec_payload.get(
                        "child_grant_id"
                    ):
                        graph.link(call_id, agent_ids[actor], "SPAWNS")
        if effect:
            affected = bool(executed and exec_payload.get("ok"))
            for resource in effect["resources"]:
                category = impact_category(effect["kind"], resource)
                imp_id = f"impact:{category}:{resource}"
                node = graph.add(
                    Node(
                        imp_id,
                        "impact",
                        resource,
                        {
                            "category": category,
                            "resource": resource,
                            "kinds": [],
                            "status": "prevented",
                        },
                        seq=decided["sequence"],
                    )
                )
                if effect["kind"] not in node.attrs["kinds"]:
                    node.attrs["kinds"].append(effect["kind"])
                if affected:
                    node.attrs["status"] = "affected"
                elif decision == "ASK" and node.attrs["status"] == "prevented":
                    node.attrs["status"] = "pending"
                edge = (
                    "ALLOWED_EFFECT"
                    if affected
                    else "PENDING_EFFECT"
                    if decision == "ASK"
                    else "PREVENTED_EFFECT"
                )
                graph.link(
                    dec_id, imp_id, edge, kind=effect["kind"], operation=effect.get("operation")
                )

    # -- focus + attack path --------------------------------------------------
    decisions = sorted(graph.of_type("decision"), key=lambda n: n.seq)
    focus = None
    if focus_decision_seq is not None:
        focus = graph.nodes.get(f"decision:{focus_decision_seq}")
    if focus is None:
        blocked = [d for d in decisions if d.attrs["decision"] != "ALLOW"]
        blocked.sort(key=lambda d: (d.attrs["provenance_risk"]["score"], d.seq))
        focus = blocked[-1] if blocked else None
    if focus is not None:
        graph.focus = focus.id
        incoming: dict[str, list[str]] = {}
        outgoing: dict[str, list[str]] = {}
        for edge in graph.edges:
            incoming.setdefault(edge.dst, []).append(edge.src)
            outgoing.setdefault(edge.src, []).append(edge.dst)
        path = {focus.id}
        queue = deque([focus.id])
        while queue:
            current = queue.popleft()
            for src in incoming.get(current, []):
                if src not in path and graph.nodes[src].type != "gateway":
                    path.add(src)
                    queue.append(src)
        for dst in outgoing.get(focus.id, []):
            path.add(dst)
        # Keep the path causal: drop benign siblings that only reach it via the agent tree.
        graph.attack_path = sorted(path, key=lambda n: (graph.nodes[n].seq, n))
    _build_timeline(
        graph,
        events,
        payloads,
        agent_ids,
        content_ids,
        collapsed,
        calls_by_seq,
        principal,
        prints,
        contents,
        envelopes,
    )
    graph.summary = _summary(graph)
    return graph


def _build_timeline(
    graph,
    events,
    payloads,
    agent_ids,
    content_ids,
    collapsed,
    calls_by_seq,
    principal,
    prints,
    contents,
    envelopes,
) -> None:
    lanes = [{"id": "user", "label": "User"}]
    for node in sorted(graph.of_type("agent"), key=lambda n: (n.attrs["depth"], n.id)):
        lanes.append({"id": node.id, "label": node.label})
    lanes.append({"id": "gw", "label": "Gateway"})
    used_servers: list[str] = []
    for event in events:
        if event["event_type"] == "TOOL_PROPOSED" and event["actor_id"] in agent_ids:
            alias = payloads[event["event_id"]]["tool"].split(".", 1)[0]
            if f"mcp:{alias}" not in used_servers and alias != "host":
                used_servers.append(f"mcp:{alias}")
    for server in used_servers:
        lanes.append({"id": server, "label": graph.nodes[server].label})
    graph.lanes = lanes
    steps: list[dict[str, Any]] = []
    call_of_exec: dict[str, str] = {}
    by_id = {e["event_id"]: e for e in events}

    def add(kind, src, dst, text, seq, **extra):
        steps.append({"seq": seq, "kind": kind, "from": src, "to": dst, "text": text, **extra})

    goal = graph.nodes.get("source:goal")
    main = next(
        (
            a
            for a in sorted(graph.of_type("agent"), key=lambda n: n.id)
            if a.attrs["role"] == "main"
        ),
        None,
    )
    if goal is not None and main is not None:
        add("message", "user", main.id, "task: " + goal.attrs["preview"][:80], -1, node=goal.id)

    for event in events:
        etype, payload, seq = event["event_type"], payloads[event["event_id"]], event["sequence"]
        actor = agent_ids.get(event["actor_id"])
        if etype == "USER_MESSAGE":
            target = next(
                (
                    a
                    for a in sorted(graph.of_type("agent"), key=lambda n: n.id)
                    if a.attrs["role"] == "main"
                ),
                None,
            )
            text = next(
                (
                    graph.nodes[content_ids[a]].attrs["preview"]
                    for a in content_ids
                    if envelopes[a]["origin"]["event_id"] == event["event_id"]
                ),
                "task",
            )
            add("message", "user", target.id if target else "gw", "task: " + text[:70], seq)
        elif etype == "TOOL_PROPOSED" and actor:
            call = graph.nodes.get(calls_by_seq.get(seq, ""))
            if call is None or call.attrs.get("trusted_probe"):
                continue
            params = call.attrs["params"]
            brief = (
                ", ".join(f"{k}={v}" for k, v in params.items()) if isinstance(params, dict) else ""
            )
            add("request", actor, "gw", f"{call.attrs['tool']}({brief[:90]})", seq, node=call.id)
        elif etype == "TOOL_CALL_DECIDED" and actor:
            dec = graph.nodes.get(f"decision:{seq}")
            if dec is None:
                continue
            note = f"{dec.attrs['decision']} · {dec.attrs['rule']} · risk {dec.attrs['provenance_risk']['level']}"
            add("note", "gw", "gw", note, seq, node=dec.id, decision=dec.attrs["decision"])
            if dec.attrs["decision"] == "BLOCK":
                add("deny", "gw", actor, f"BLOCK {dec.attrs['reason']}", seq, node=dec.id)
            elif dec.attrs["decision"] == "ASK":
                add("message", "gw", "user", "approval requested", seq, node=dec.id)
        elif etype == "EXECUTION_RESULT" and actor:
            proposed = (
                by_id.get(by_id[event["parent_event_ids"][0]]["parent_event_ids"][0])
                if (
                    event["parent_event_ids"]
                    and by_id[event["parent_event_ids"][0]]["parent_event_ids"]
                )
                else None
            )
            call_id = calls_by_seq.get(proposed["sequence"]) if proposed else None
            tool = payload.get("tool", "")
            if call_id:
                call_of_exec[event["event_id"]] = call_id
            if tool == "host.delegate":
                child = next(
                    (e.dst for e in graph.edges if e.src == call_id and e.type == "SPAWNS"), None
                )
                if child:
                    add("spawn", "gw", child, "spawn with narrowed grant", seq, node=child)
            elif payload.get("ok"):
                server = "mcp:" + tool.split(".", 1)[0]
                add("request", "gw", server, f"invoke {tool.split('.', 1)[-1]}", seq, node=call_id)
                add("reply", server, "gw", "result", seq)
        elif etype == "DETECTION_FINDING":
            finding = payload["finding"]
            aid = (
                collapsed.get(event["artifact_ids"][0], event["artifact_ids"][0])
                if event["artifact_ids"]
                else None
            )
            spans = [
                e.dst
                for e in graph.edges
                if aid in content_ids and e.src == content_ids[aid] and e.type == "CONTAINS"
            ]
            where = ""
            if spans:
                s = graph.nodes[spans[0]].attrs
                where = f" @chars {s['char_start']}-{s['char_end']} tokens {s['token_start']}-{s['token_end']}"
            add(
                "note",
                "gw",
                "gw",
                f"injection {finding['attack_family']}{where}",
                seq,
                alert=True,
                node=spans[0] if spans else content_ids.get(aid),
            )
        elif etype == "MODEL_EXPOSED" and actor:
            if event["artifact_ids"] and event["artifact_ids"][0] in collapsed:
                continue  # structured twin of an already shown result
            aid = event["artifact_ids"][0] if event["artifact_ids"] else None
            node = graph.nodes.get(content_ids.get(aid, ""))
            label = ""
            if node is not None:
                label = f"{node.attrs['origin_type']} [{node.attrs['confidentiality']}]"
                if node.attrs["findings"]:
                    label += " ⚠tainted"
            if payload.get("tool") == "host.delegate":
                child_lane = next(
                    (a for a in graph.of_type("agent") if a.attrs.get("parent") == actor), None
                )
                add(
                    "reply",
                    child_lane.id if child_lane else "gw",
                    actor,
                    "child result " + label,
                    seq,
                    node=node.id if node else None,
                )
            else:
                add("reply", "gw", actor, "result " + label, seq, node=node.id if node else None)
        elif etype == "RESOURCE_AFFECTED" and actor:
            add("note", "gw", "gw", "effect " + ", ".join(payload.get("resources", []))[:80], seq)
    graph.timeline = steps


def _summary(graph: ProvenanceGraph) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for node in graph.nodes.values():
        counts[node.type] = counts.get(node.type, 0) + 1
    edge_counts: dict[str, int] = {}
    for edge in graph.edges:
        edge_counts[edge.type] = edge_counts.get(edge.type, 0) + 1
    summary: dict[str, Any] = {"node_counts": counts, "edge_counts": edge_counts}
    if graph.focus:
        focus = graph.nodes[graph.focus]
        path = [graph.nodes[n] for n in graph.attack_path]
        summary["focus"] = {
            "decision": focus.attrs["decision"],
            "reason": focus.attrs["reason"],
            "rule": focus.attrs["rule"],
            "risk": focus.attrs["provenance_risk"],
            "explanation": focus.attrs["explanation"],
        }
        summary["trigger_sources"] = [
            {"id": n.id, "kind": n.attrs["kind"], "locator": n.attrs["locator"]}
            for n in path
            if n.type == "source"
        ]
        summary["agent_chain"] = [
            {"id": n.id, "label": n.label, "role": n.attrs["role"], "depth": n.attrs["depth"]}
            for n in sorted((n for n in path if n.type == "agent"), key=lambda n: n.attrs["depth"])
        ]
        summary["mcp_servers"] = sorted(
            {
                graph.nodes[e.dst].attrs["alias"]
                for e in graph.edges
                if e.type == "ROUTED_TO"
                and e.src in graph.attack_path
                and e.dst.startswith("mcp:")
                and graph.nodes[e.dst].attrs["alias"] != "host"
            }
        )
        summary["payload_spans"] = [
            {
                "id": n.id,
                **{
                    k: n.attrs[k]
                    for k in (
                        "char_start",
                        "char_end",
                        "token_start",
                        "token_end",
                        "byte_start",
                        "byte_end",
                        "precision",
                        "excerpt",
                    )
                },
            }
            for n in path
            if n.type == "span"
        ]
        impacts = [n for n in graph.of_type("impact")]
        summary["impact_scope"] = {
            category: sorted(
                {
                    f"{n.attrs['resource']} ({n.attrs['status']})"
                    for n in impacts
                    if n.attrs["category"] == category
                }
            )
            for category in ("local_file", "credential_store", "network", "git_repo", "memory")
        }
    return summary


def is_acyclic(graph: ProvenanceGraph) -> bool:
    indegree = {node: 0 for node in graph.nodes}
    outgoing: dict[str, list[str]] = {}
    for edge in graph.edges:
        indegree[edge.dst] += 1
        outgoing.setdefault(edge.src, []).append(edge.dst)
    queue = deque(sorted(n for n, d in indegree.items() if d == 0))
    seen = 0
    while queue:
        current = queue.popleft()
        seen += 1
        for dst in outgoing.get(current, []):
            indegree[dst] -= 1
            if indegree[dst] == 0:
                queue.append(dst)
    return seen == len(graph.nodes)


def stable_json(graph: ProvenanceGraph) -> str:
    """Graph JSON with run-specific ULIDs replaced by first-appearance aliases."""
    text = graph.to_json()
    aliases: dict[str, str] = {}

    def alias(match: re.Match) -> str:
        return aliases.setdefault(match.group(0), f"<id{len(aliases) + 1}>")

    return ULID.sub(alias, text)
