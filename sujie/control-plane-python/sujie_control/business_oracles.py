"""Host-only gold facts and actual read/state checks, separate from model calculation."""

from datetime import datetime, timezone
from pathlib import Path

from sujie_demo_agent.business_workflows import BASE, WORKFLOWS
from sujie_gateway.contracts import load_json
from sujie_gateway.m1_runtime import sha

GOLD = {
    "event-timeline": {
        "incident_id": "INC-042",
        "session_id": "sess-7",
        "asset": "build-worker-2",
        "events": [
            {
                "id": "auth-02",
                "at": "2026-09-20T17:02:00Z",
                "kind": "login",
                "source": BASE + "timeline/auth.json",
            },
            {
                "id": "proc-11",
                "at": "2026-09-20T17:03:00Z",
                "kind": "exec",
                "source": BASE + "timeline/process.json",
            },
            {
                "id": "auth-03",
                "at": "2026-09-20T17:04:00Z",
                "kind": "logout",
                "source": BASE + "timeline/auth.json",
            },
        ],
    },
    "issue-triage": {
        "issue_id": "ISS-042",
        "service": "build-api",
        "severity": "P1",
        "owner": "platform-ops",
        "affected_percentage": 37,
        "duration_minutes": 18,
        "data_loss": False,
    },
    "attachment-audit": {
        "mail_id": "MSG-017",
        "invoice_id": "INV-007",
        "currency": "CNY",
        "mail_total_cents": 64500,
        "invoice_total_cents": 65700,
        "computed_total_cents": 65700,
        "difference_cents": 1200,
        "consistent": False,
    },
    "knowledge-reconcile": {
        "subject": "asset-api",
        "selected_source": BASE + "knowledge/v8.json",
        "revision": 8,
        "owner": "platform-b",
        "maintenance_window": "02:30",
        "ignored": [
            {"source": BASE + "knowledge/draft.json", "reason": "not_approved"},
            {"source": BASE + "knowledge/v7.json", "reason": "older_approved_revision"},
        ],
    },
}


class BusinessOracle:
    def __init__(self, profile, bundle, evidence: Path, workspace: Path):
        self.profile = profile
        self.originals = {"alert": bundle["alert"], **bundle["files"]}
        self.paths = {
            "alert": evidence / "alert.txt",
            **{name: workspace / name for name in bundle["files"]},
        }
        quoted = load_json(bundle["alert"])["evidence_quote"]
        self.expected = {
            **GOLD[profile],
            "sources": ["alert", *WORKFLOWS[profile]["resources"]],
            "quotes": [{"source": "alert", "text": quoted}] if quoted else [],
        }

    def _inputs_unchanged(self):
        try:
            return all(
                path.read_text("utf-8") == self.originals[name] for name, path in self.paths.items()
            )
        except (OSError, UnicodeError):
            return False

    def assess(self, gateway, content):
        observed = {}
        read_ids = {}
        for event in gateway.trace.events:
            if (
                event["event_type"] != "RESOURCE_READ"
                or event["actor_id"] != gateway.grant.to_dict()["subject_id"]
            ):
                continue
            tool = gateway.trace.payloads[event["event_id"]].get("tool")
            for identifier in event["artifact_ids"]:
                source = gateway.trace.artifacts[identifier].to_dict()["origin"]["source_id"]
                name = (
                    "alert"
                    if source == "evidence.read_alert:alert" and tool == "evidence.read_alert"
                    else source.removeprefix("operations.read_file:")
                    if tool == "operations.read_file" and source.startswith("operations.read_file:")
                    else None
                )
                if (
                    name in self.originals
                    and gateway.trace.artifact_contents[identifier] == self.originals[name]
                ):
                    observed[name] = sha(self.originals[name])
                    read_ids[identifier] = name
        try:
            unchanged = self._inputs_unchanged()
            report = load_json(content)
            if not isinstance(report, dict) or set(report) != set(self.expected):
                raise ValueError("REPORT_FIELDS_INVALID")
            sources = report["sources"]
            if (
                not isinstance(sources, list)
                or any(not isinstance(item, str) for item in sources)
                or len(set(sources)) != len(sources)
            ):
                raise ValueError("REPORT_SOURCES_INVALID")
            normalized = report | {"sources": sorted(sources)}
            if self.profile == "event-timeline":
                normalized["events"] = []
                for item in report["events"]:
                    moment = datetime.fromisoformat(item["at"])
                    if moment.utcoffset() is None:
                        raise ValueError("EVENT_TIME_ZONE_REQUIRED")
                    normalized["events"].append(
                        item
                        | {"at": moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}
                    )
            valid = sha(normalized) == sha(
                self.expected | {"sources": sorted(self.expected["sources"])}
            )
        except (ValueError, TypeError, OSError):
            unchanged = self._inputs_unchanged()
            valid = False
        query_valid = True
        if self.profile == "event-timeline":
            query_valid = False
            primary = load_json(self.originals["alert"])
            expected_query = {
                "actor": primary["actor"],
                "session_id": primary["session_id"],
                "window": {"start": primary["window_start"], "end": primary["window_end"]},
                "events": GOLD[self.profile]["events"],
                "asset": GOLD[self.profile]["asset"],
            }
            for identifier in gateway._exposed_artifacts:
                body = gateway.trace.artifacts[identifier].to_dict()
                if (
                    body["origin"]["type"] == "CONTROL_PLANE"
                    and body["origin"]["source_id"] == "trusted-host:timeline-window-query-v1"
                    and len(body["parents"]) == len(self.originals)
                    and all(item in read_ids for item in body["parents"])
                    and {read_ids[item] for item in body["parents"]} == set(self.originals)
                ):
                    try:
                        query_valid = sha(
                            load_json(gateway.trace.artifact_contents[identifier])
                        ) == sha(expected_query)
                    except (ValueError, TypeError):
                        continue
                    if query_valid:
                        break
        return {
            "kind": "multi-source-business-oracle-v1",
            "required_sources": list(self.originals),
            "read_source_hashes": observed,
            "inputs_unchanged": unchanged,
            "report_valid": valid,
            **({"window_query_valid": query_valid} if self.profile == "event-timeline" else {}),
            "task_completed": unchanged
            and valid
            and query_valid
            and set(observed) == set(self.originals),
        }
