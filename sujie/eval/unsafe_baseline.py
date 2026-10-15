"""Deliberately unprotected MCP baseline for sealed synthetic evaluation only."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sujie_gateway.m1_runtime import StdioMCPProxy


class UnsafeGateway:
    """Same Host interface, direct MCP effects, no policy or provenance enforcement."""

    def __init__(self, proxy: StdioMCPProxy) -> None:
        self.proxy = proxy
        self._exposed_artifacts: set[str] = set()
        self.trace = SimpleNamespace(events=[], payloads={})

    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            data = await self.proxy.invoke(tool, args)
        except RuntimeError:
            return {"ok": False, "decision": "ALLOW", "code": "TOOL_EXECUTION_FAILED"}
        return {"ok": True, "decision": "ALLOW", "data": data}

    def record_model_output(
        self,
        content: str,
        *,
        transformation: str = "SUMMARY",
        input_artifacts: tuple[str, ...] | None = None,
        response_event_id: str | None = None,
    ) -> None:
        return None

    def record_visible_plan(
        self, calls: list[dict], content_hash: str, *, response_event_id: str | None = None
    ) -> None:
        return None

    async def record_host_block(self, tool: str, args: dict, code: str) -> dict:
        return {"ok": False, "decision": "BLOCK", "code": code}

    def record_semantic_finding(
        self, content: str, reason_code: str, *, detector_version: str
    ) -> None:
        return None
