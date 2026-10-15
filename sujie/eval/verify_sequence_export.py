"""Recompute an assessment from exported event metadata; no authenticity claim."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway-python/src"))

from sujie_gateway.sequence_alignment import assess_sequence  # noqa: E402
from verify_operator_export import verify  # noqa: E402


def recompute(document: dict) -> dict:
    checked = verify(document)
    task = document["payload"]["task"]
    if "assessment" not in task:
        raise ValueError("SEQUENCE_ASSESSMENT_UNAVAILABLE")
    events = task["events"]
    expected = assess_sequence(
        task["contract"],
        events,
        {event["event_id"]: event["details"] for event in events},
        {artifact["artifact_id"]: artifact for artifact in task["artifacts"]},
    )
    if expected != task["assessment"]:
        raise ValueError("SEQUENCE_ASSESSMENT_MISMATCH")
    return {
        "ok": True,
        "scope": "EXPORTED_METADATA_CONSISTENCY_NOT_SIGNED_AUTHENTICITY_OR_ASR",
        "task_id": checked["task_id"],
        "conclusion": expected["conclusion"],
        "proposals": len(expected["tool_sequence"]),
        "visible_plans": len(expected["visible_plans"]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    args = parser.parse_args()
    if args.export.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("EXPORT_TOO_LARGE")
    print(json.dumps(recompute(json.loads(args.export.read_bytes())), ensure_ascii=False))
