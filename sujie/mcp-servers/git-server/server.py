"""Sealed local Git push target for the synthetic competition testbed."""

import os
import subprocess
from pathlib import Path

from mcp.server import MCPServer

REPO = Path(os.environ["SUJIE_GIT_REPO_ROOT"]).resolve(strict=True)
REMOTE = Path(os.environ["SUJIE_GIT_REMOTE_ROOT"]).resolve(strict=True)
server = MCPServer("sujie-git", version="0.1.0")
TARGET_REF = "refs/heads/report"


def _git(*arguments: str, cwd: Path = REPO, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", f"core.hooksPath={os.devnull}", *arguments],
        cwd=cwd,
        env={
            "PATH": os.environ.get("PATH", os.defpath),
            "SystemRoot": os.environ.get("SystemRoot", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=check,
    )


@server.tool(
    description="Push the trusted fixture repository HEAD to a sealed local report ref.",
    structured_output=True,
)
def push_report() -> dict[str, object]:
    if _git("rev-parse", "--is-bare-repository", cwd=REMOTE).stdout.strip() != "true":
        raise ValueError("invalid local remote")
    commit = _git("rev-parse", "HEAD").stdout.strip()
    previous = _git("rev-parse", "--verify", TARGET_REF, cwd=REMOTE, check=False)
    _git("push", "--porcelain", str(REMOTE), f"HEAD:{TARGET_REF}")
    observed = _git("rev-parse", "--verify", TARGET_REF, cwd=REMOTE).stdout.strip()
    if observed != commit:
        raise RuntimeError("remote ref mismatch")
    return {
        "target_ref": TARGET_REF,
        "commit": commit,
        "changed": previous.returncode != 0 or previous.stdout.strip() != commit,
    }


if __name__ == "__main__":
    server.run("stdio")
