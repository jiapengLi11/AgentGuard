"""Check a redacted operator export's digest and links, not benchmark authenticity."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gateway-python/src"))

from sujie_gateway.contracts import load_json, snapshot_hash  # noqa: E402


def verify(document: dict) -> dict:
    payload = document["payload"]
    if document["export_hash"] != snapshot_hash(payload):
        raise ValueError("EXPORT_HASH_MISMATCH")
    if payload["schema_version"] != "sujie-operator-export-v1" or payload["mode"] not in {
        "sealed-local-demo-fixed-actions",
        "sealed-local-model-report",
        "sealed-local-model-ioc-transfer",
        "sealed-local-model-web-report",
        "sealed-local-model-artifact-verify",
        "sealed-local-model-git-review",
        "sealed-local-model-git-publish",
        "sealed-local-model-delegated-report",
        "sealed-local-model-memory-review",
        "sealed-local-model-memory-update",
        "sealed-local-model-event-timeline",
        "sealed-local-model-issue-triage",
        "sealed-local-model-attachment-audit",
        "sealed-local-model-knowledge-reconcile",
    }:
        raise ValueError("EXPORT_MODE_UNSUPPORTED")
    task = payload["task"]
    seen_artifacts, seen_events = set(), set()
    for artifact in task["artifacts"]:
        identifier = artifact["artifact_id"]
        if identifier in seen_artifacts or not set(artifact["parents"]) <= seen_artifacts:
            raise ValueError("INVALID_ARTIFACT_GRAPH")
        seen_artifacts.add(identifier)
    for event in task["events"]:
        identifier = event["event_id"]
        if (
            identifier in seen_events
            or not set(event["parent_event_ids"]) <= seen_events
            or not set(event["artifact_ids"]) <= seen_artifacts
        ):
            raise ValueError("INVALID_EVENT_GRAPH")
        seen_events.add(identifier)
    return {
        "ok": True,
        "scope": "export-integrity-and-links-only-not-signed-or-benchmark-ASR",
        "task_id": task["id"],
        "events": len(seen_events),
        "artifacts": len(seen_artifacts),
        "metrics": task["metrics"],
        "oracle": task["oracle"],
        "export_hash": document["export_hash"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    args = parser.parse_args()
    try:
        if args.export.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("EXPORT_TOO_LARGE")
        result = verify(load_json(args.export.read_bytes()))
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({"ok": False, "code": "EXPORT_VERIFICATION_FAILED"}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
