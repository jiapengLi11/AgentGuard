"""Real stdio MCP network executor with a trusted, immutable request policy."""

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "sandbox")]

from mcp.server import MCPServer  # noqa: E402
from network_executor import fetch as execute_fetch  # noqa: E402
from sujie_gateway.network_policy import NetworkPolicy  # noqa: E402

policy = NetworkPolicy.from_dict(json.loads(Path(os.environ["SUJIE_NETWORK_POLICY"]).read_bytes()))
server = MCPServer("sujie-network", version=policy.server_version)


@server.tool(
    description="Fetch a bounded UTF-8 response under the registered network policy.",
    structured_output=True,
)
def fetch(
    url: str, method: str = "GET", headers: dict[str, str] | None = None, body: str = ""
) -> dict[str, Any]:
    return execute_fetch(
        policy, {"url": url, "method": method, "headers": headers or {}, "body": body}
    )


if __name__ == "__main__":
    server.run(transport="stdio")
