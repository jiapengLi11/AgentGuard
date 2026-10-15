"""Local metadata-only MCP fixture; never imports an upstream benchmark module."""

import os
from pathlib import Path

from mcp.server import MCPServer

description_path = Path(os.environ["SUJIE_CATALOG_DESCRIPTION_FILE"])
description = description_path.read_text("utf-8")
if len(description) > 100_000:
    raise ValueError("DESCRIPTION_TOO_LARGE")

server = MCPServer("sujie-eval-catalog", version="1.0.0")


@server.tool(description=description, structured_output=True)
def search(query: str) -> dict[str, str]:
    """A no-effect tool. The protocol test never calls it."""
    return {"query": query}


extra_name = os.environ.get("SUJIE_CATALOG_EXTRA_NAME")
if extra_name:
    extra_description = Path(os.environ["SUJIE_CATALOG_EXTRA_DESCRIPTION_FILE"]).read_text("utf-8")
    if len(extra_description) > 100_000:
        raise ValueError("DESCRIPTION_TOO_LARGE")

    @server.tool(name=extra_name, description=extra_description, structured_output=True)
    def extra(query: str) -> dict[str, str]:
        """Another no-effect tool. The protocol test never calls it."""
        return {"query": query}


if __name__ == "__main__":
    server.run("stdio")
