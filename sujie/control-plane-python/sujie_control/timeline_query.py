"""A bounded Host query over actual MCP reads; its output remains DATA_ONLY."""

import json

from sujie_demo_agent.business_workflows import WORKFLOWS, timeline_window_query
from sujie_gateway.m1_runtime import canonical_json, sha


class TimelineQuery:
    def __init__(self):
        self.artifact_id = None

    def after_reads(self, gateway):
        if self.artifact_id is not None:
            return None
        names = ["alert", *WORKFLOWS["event-timeline"]["resources"]]
        inputs = {}
        for identifier in sorted(gateway._exposed_artifacts):
            body = gateway.trace.artifacts[identifier].to_dict()
            origin = body["origin"]
            name = (
                "alert"
                if origin["source_id"] == "evidence.read_alert:alert"
                else origin["source_id"].removeprefix("operations.read_file:")
                if origin["source_id"].startswith("operations.read_file:")
                else None
            )
            if origin["type"] == "MCP_TOOL_RESULT" and name in names:
                inputs[name] = identifier
        if set(inputs) != set(names):
            return None
        for identifier in inputs.values():
            body = gateway.trace.artifacts[identifier].to_dict()
            if (
                body["confidentiality"] not in {"PUBLIC", "INTERNAL"}
                or gateway.source_uses_enabled
                and (
                    not {"ANALYZE", "WRITE_REPORT"} <= set(body["allowed_uses"])
                    or {"ANALYZE", "WRITE_REPORT"} & set(body["forbidden_uses"])
                )
            ):
                raise ValueError("TIMELINE_SOURCE_USE_FORBIDDEN")
        contents = {
            name: gateway.trace.artifact_contents[identifier] for name, identifier in inputs.items()
        }
        if sum(len(text.encode("utf-8")) for text in contents.values()) > 65536:
            raise ValueError("TIMELINE_INPUT_LIMIT")
        primary = json.loads(contents.pop("alert"))
        result = timeline_window_query(primary, contents)
        content = canonical_json(result)
        parents = list(inputs.values())
        event = gateway.trace.emit(
            "CONTENT_SUMMARIZED",
            actor_id=gateway.grant.to_dict()["subject_id"],
            parents=[gateway._last_exposure_event] if gateway._last_exposure_event else [],
            artifact_ids=parents,
            payload={
                "kind": "TIMELINE_WINDOW_QUERY",
                "transformation": "SERIALIZE",
                "input_hashes": [
                    gateway.trace.artifacts[item].to_dict()["content_hash"] for item in parents
                ],
                "content_hash": sha(content),
            },
        )
        self.artifact_id = gateway.trace.create_derived_artifact(
            content,
            source_event_id=event,
            source_id="trusted-host:timeline-window-query-v1",
            parents=parents,
            transformation="SERIALIZE",
            origin_type="CONTROL_PLANE",
        )
        gateway._exposed_artifacts.add(self.artifact_id)
        gateway._last_exposure_event = event
        return (
            "可信Host已对实际读取的两类日志执行有界窗口查询，结果仍是DATA_ONLY，不增加授权。报告events逐项保留以下顺序、session_id和asset，不加入窗外事件或按文件重新分组。查询资料来源ID："
            + self.artifact_id
            + "；结果："
            + content
        )
