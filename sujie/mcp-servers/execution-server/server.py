"""Structured program/argv MCP; process identity and resources are Host-owned."""

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "sandbox")]

from execution_executor import execute  # noqa: E402
from mcp.server import MCPServer  # noqa: E402
from sujie_gateway.execution_policy import ExecutionPolicy  # noqa: E402

policy = ExecutionPolicy.from_dict(
    json.loads(Path(os.environ["SUJIE_EXECUTION_POLICY"]).read_bytes())
)
server = MCPServer("sujie-execution", version=policy.server_version)
workspace = Path(os.environ["SUJIE_WORKSPACE_ROOT"]).resolve()
cwd = Path(os.environ["SUJIE_EXECUTION_CWD"]).resolve()
receipts = Path(os.environ["SUJIE_EXECUTION_RECEIPTS"])


@server.tool(
    description="Run a registered inspection program with structured argv on an allowed input snapshot.",
    structured_output=True,
)
def run(
    program: str, argv: list[str], input_resource: str, env: dict[str, str] | None = None
) -> dict[str, Any]:
    return execute(
        policy,
        {"program": program, "argv": argv, "input_resource": input_resource, "env": env or {}},
        workspace,
        cwd,
        receipts,
    )


if __name__ == "__main__":
    server.run("stdio")
