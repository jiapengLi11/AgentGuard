"""Local Git delivery MCP with a sealed snapshot and explicit ref lease."""

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "gateway-python/src"), str(ROOT / "sandbox")]

from mcp.server import MCPServer  # noqa: E402
from sealed_git import GitRunner, SealedGit  # noqa: E402
from sujie_gateway.git_policy import GitPolicy  # noqa: E402

policy = GitPolicy.from_dict(json.loads(Path(os.environ["SUJIE_GIT_POLICY"]).read_bytes()))
runner = GitRunner(
    Path(os.environ["SUJIE_GIT_REPO_ROOT"]),
    Path(os.environ["SUJIE_GIT_REMOTE_ROOT"]),
    Path(os.environ["SUJIE_GIT_HOOKS_ROOT"]),
    timeout=policy.to_dict()["timeout_seconds"],
)
executor = SealedGit(runner, policy, Path(os.environ["SUJIE_GIT_RECEIPTS"]))
server = MCPServer("sujie-git-delivery", version=policy.server_version)


@server.tool(
    description="Inspect the pinned commit README and configuration diff in the sealed repository.",
    structured_output=True,
)
def inspect() -> dict[str, Any]:
    return executor.inspect()


@server.tool(
    description="Read the current sealed Git snapshot validity without updating refs.",
    structured_output=True,
)
def state() -> dict[str, Any]:
    return executor.state()


@server.tool(
    description="Push the exact registered commit, ref and expected previous ref value to the sealed local remote.",
    structured_output=True,
)
def push(remote: str, ref: str, commit: str, expected_old: str, state_hash: str) -> dict[str, Any]:
    return executor.push(
        {
            "remote": remote,
            "ref": ref,
            "commit": commit,
            "expected_old": expected_old,
            "state_hash": state_hash,
        }
    )


if __name__ == "__main__":
    server.run("stdio")
