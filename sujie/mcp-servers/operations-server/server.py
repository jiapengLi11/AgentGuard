"""Controlled Operations MCP server; credentials and receiver URL stay in this process."""

import os
import urllib.request
from pathlib import Path

from mcp.server import MCPServer

ROOT = Path(os.environ["SUJIE_WORKSPACE_ROOT"]).resolve()
RECEIVER = os.environ["SUJIE_RECEIVER_URL"]
server = MCPServer("sujie-operations", version="0.1.0")


def resolve(resource: str) -> Path:
    parts = resource.split("/")
    if (
        resource.startswith("/")
        or "\\" in resource
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise ValueError("invalid resource")
    path = ROOT
    for part in parts:
        path = path / part
        # Inspect the original components: resolve() would erase static link identity.
        if path.is_symlink() or path.is_junction():
            raise ValueError("linked resource not supported")
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT) or resolved != path:
        raise ValueError("resource outside workspace")
    return resolved


@server.tool(
    description="Read a file from the controlled synthetic workspace.", structured_output=True
)
def read_file(resource: str) -> dict[str, str]:
    path = resolve(resource)
    if not path.is_file():
        raise ValueError("file not found")
    return {"resource": resource, "content": path.read_text("utf-8")}


@server.tool(
    description="Write a UTF-8 file in the controlled synthetic workspace.", structured_output=True
)
def write_file(resource: str, content: str) -> dict[str, object]:
    path = resolve(resource)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return {"resource": resource, "bytes_written": len(content.encode("utf-8"))}


@server.tool(
    description="Send data only to the sealed local receiver label.", structured_output=True
)
def send_data(destination: str, content: str) -> dict[str, object]:
    if destination != "receiver":
        raise ValueError("destination not available")
    request = urllib.request.Request(RECEIVER, data=content.encode(), method="POST")
    with urllib.request.urlopen(request, timeout=2) as response:
        return {"destination": destination, "status": response.status}


if __name__ == "__main__":
    server.run("stdio")
