"""Additional bounded rule signal for deferred memory instructions, not a classifier score."""

import re

from .contracts import DetectionFinding

VERSION = "memory-deferred-rules-v1"
DEFERRED = re.compile(
    r"\b(?:when\s+a\s+future\s+user|next\s+time|when\b[^\n]{0,120}\bmentions)\b|(?:下次|未来|再次).{0,60}(?:用户|提到|询问)",
    re.I,
)
OVERRIDE = re.compile(
    r"\b(?:silently\s+(?:set|change|replace)|ignore\s+(?:the\s+)?new\s+(?:document|record)|conceal|falsify)\b|(?:暗中|悄悄|伪造|忽略新记录|替换事实)",
    re.I,
)


def deferred_memory_finding(content: str, view: str, artifact_id: str, finding_id: str):
    if len(content) > 32768 or not DEFERRED.search(view) or not OVERRIDE.search(view):
        return None
    return DetectionFinding(
        {
            "schema_version": "1.0",
            "finding_id": finding_id,
            "attack_source": "MEMORY",
            "attack_family": "MEMORY_POISONING",
            "spans": [{"artifact_id": artifact_id, "start": 0, "end": len(content)}],
            "normalized_view": f"evidence://view/{artifact_id}/nfkc-v1",
            "confidence": 0.7,
            "reasons": [
                "memory_conditions_future_behavior_and_silently_overrides_current_evidence"
            ],
            "detector_version": VERSION,
        }
    )
