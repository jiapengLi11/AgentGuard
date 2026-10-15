"""Bounded, explainable first-pass scan of untrusted tool output."""

from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import unquote

from .contracts import DetectionFinding

DETECTOR_VERSION = "rules-v0.3"
MAX_SCAN_CHARS = 1_000_000
OVERRIDE_PATTERNS = (
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions", re.I),
    re.compile(r"(?:忽略|无视)(?:原|之前|先前|以上|所有|当前)?(?:任务|指令|规则)"),
)
AGENT_DIRECTIVE = re.compile(
    r"\b(?:you\s+)?(?:must|should|always|please)\s+"
    r"(?:(?:first|also|now|then|automatically|immediately)\s+){0,3}"
    r"(?:call|execute|run|send|access|update|modify|change|redirect|fetch|delete|upload|display|state|use|ignore|set|perform|make|clean|read|remove)\b",
    re.I,
)
PARAMETER_REWRITE = re.compile(
    r"\b(?:query|parameter|argument|input)\s+is\s+(?:automatically\s+)?"
    r"(?:modified|changed|rewritten|enhanced)\s+to\s+(?:include|add|replace|use)\b",
    re.I,
)
SELF_TOOL_GUIDANCE = re.compile(
    r"\s+this\s+tool\s+when(?:ever)?\s+(?:(?:the\s+)?user\b|asked\b)", re.I
)
CONCEALMENT_DIRECTIVE = re.compile(
    r"\b(?:must|should|do)\s+not\s+(?:inform|tell|notify|mention)\s+(?:the\s+)?user\b",
    re.I,
)


def normalized_view(content: str) -> str:
    """Make an inspection view while leaving the stored source untouched."""
    view = unicodedata.normalize("NFKC", content[:MAX_SCAN_CHARS])[:MAX_SCAN_CHARS]
    view = "".join(char for char in view if unicodedata.category(char) != "Cf")
    for _ in range(2):
        decoded = unicodedata.normalize("NFKC", html.unescape(unquote(view)))[:MAX_SCAN_CHARS]
        if decoded == view:
            break
        view = decoded
    return view


def detect_indirect(
    content: str,
    artifact_id: str,
    finding_id: str,
    *,
    attack_source: str = "INDIRECT",
) -> tuple[str, DetectionFinding | None]:
    """Return a coarse source span; normalized offsets are not raw offsets."""
    view = normalized_view(content)
    override = any(pattern.search(view) for pattern in OVERRIDE_PATTERNS)
    directive = bool(CONCEALMENT_DIRECTIVE.search(view) or PARAMETER_REWRITE.search(view))
    for match in AGENT_DIRECTIVE.finditer(view):
        # A catalog may legitimately tell the agent when to use the described
        # tool. Exempt that one match, while still scanning for other commands.
        if match.group().lower().rstrip().endswith(("call", "use")) and SELF_TOOL_GUIDANCE.match(
            view, match.end()
        ):
            continue
        directive = True
        break
    if not override and not directive:
        return view, None
    finding = DetectionFinding(
        {
            "schema_version": "1.0",
            "finding_id": finding_id,
            "attack_source": attack_source,
            "attack_family": "CONTEXT_HIJACK" if override else "TOOL_POISONING",
            "spans": [{"artifact_id": artifact_id, "start": 0, "end": len(content)}],
            "normalized_view": f"evidence://view/{artifact_id}/nfkc-v1",
            "confidence": 0.9,
            "reasons": [
                "untrusted_text_requests_instruction_override"
                if override
                else "untrusted_text_directs_agent_action"
            ],
            "detector_version": DETECTOR_VERSION,
        }
    )
    return view, finding
