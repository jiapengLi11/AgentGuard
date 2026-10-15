"""Static-text quarantine baseline for the sealed synthetic alert workflow.

This intentionally has no contract, grant, or provenance enforcement. A rule hit
quarantines later file reads and transfers while allowing the local report.
"""

from __future__ import annotations

from typing import Any

from sujie_gateway.detection import detect_indirect
from sujie_gateway.m1_runtime import new_id
from unsafe_baseline import UnsafeGateway


class StaticOnlyGateway(UnsafeGateway):
    def __init__(self, proxy) -> None:
        super().__init__(proxy)
        self._quarantined = False

    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if self._quarantined and tool in {"operations.read_file", "operations.send_data"}:
            return {"ok": False, "decision": "BLOCK", "code": "STATIC_QUARANTINE"}
        result = await super().call(tool, args)
        if tool == "evidence.read_alert" and result.get("ok"):
            content = result["data"].get("content")
            if isinstance(content, str):
                event_id = new_id()
                _, finding = detect_indirect(content, event_id, new_id())
                if finding is not None:
                    self._quarantined = True
                    self.trace.events.append(
                        {"event_id": event_id, "event_type": "DETECTION_FINDING"}
                    )
                    self.trace.payloads[event_id] = {"finding": finding.to_dict()}
        return result
