"""Versioned evidence memory; the Host owns its sealed per-session policy."""

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "sandbox")]

from mcp.server import MCPServer  # noqa: E402
from sujie_gateway.memory_policy import MemoryPolicy  # noqa: E402
from versioned_memory import VersionedMemory  # noqa: E402

policy = MemoryPolicy.from_dict(json.loads(Path(os.environ["SUJIE_MEMORY_POLICY"]).read_bytes()))
store = VersionedMemory(
    Path(os.environ["SUJIE_MEMORY_DB"]), policy, Path(os.environ["SUJIE_MEMORY_RECEIPTS"])
)
server = MCPServer("sujie-versioned-memory", version=policy.server_version)


@server.tool(
    description="Read the current bounded evidence memory and pinned revision/hash.",
    structured_output=True,
)
def read(key: str) -> dict[str, Any]:
    return store.read({"key": key})


@server.tool(
    description="Append the registered exact evidence as the next revision, comparing the previous revision/hash. Existing history is retained.",
    structured_output=True,
)
def write(key: str, content: str, expected_revision: int, expected_hash: str) -> dict[str, Any]:
    return store.write(
        {
            "key": key,
            "content": content,
            "expected_revision": expected_revision,
            "expected_hash": expected_hash,
        }
    )


if __name__ == "__main__":
    server.run("stdio")
