"""Controlled Evidence MCP server. It only reads named synthetic alert documents."""

import os
from pathlib import Path

from mcp.server import MCPServer

ROOT = Path(os.environ["SUJIE_EVIDENCE_ROOT"]).resolve()
server = MCPServer("sujie-evidence", version="0.1.0")


@server.tool(
    description="Read a synthetic alert document as untrusted evidence.", structured_output=True
)
def read_alert(alert_id: str) -> dict[str, str]:
    if not alert_id.replace("-", "").isalnum():
        raise ValueError("invalid alert id")
    original = ROOT / f"{alert_id}.txt"
    if original.is_symlink() or original.is_junction():
        raise ValueError("linked alert not supported")
    path = original.resolve()
    if path != original or path.parent != ROOT or not path.is_file():
        raise ValueError("alert not found")
    return {"alert_id": alert_id, "content": path.read_text("utf-8"), "trust": "UNTRUSTED"}


if __name__ == "__main__":
    server.run("stdio")
