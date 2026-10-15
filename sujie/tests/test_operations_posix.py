"""Run on Linux CI/container to verify the descriptor-based file boundary."""

import os
import runpy
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1] / "mcp-servers/operations-server/server.py"


@pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor APIs required")
def test_posix_file_tools_reject_symlinks_and_hardlinks(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    case = workspace / "case-001"
    output = case / "output"
    output.mkdir(parents=True)
    secret = case / "secret.txt"
    secret.write_text("SYNTHETIC-SECRET", "utf-8")
    (case / "alias.txt").symlink_to(secret)
    os.link(secret, case / "hardlink.txt")
    (output / "report.txt").symlink_to(secret)
    monkeypatch.setenv("SUJIE_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("SUJIE_RECEIVER_URL", "http://127.0.0.1:9/upload")
    tools = runpy.run_path(str(SERVER), run_name="sujie_operations_test")

    with pytest.raises(OSError):
        tools["read_file"]("case-001/alias.txt")
    with pytest.raises(ValueError, match="not a regular file"):
        tools["read_file"]("case-001/hardlink.txt")
    with pytest.raises(ValueError, match="not a regular file"):
        tools["write_file"]("case-001/output/report.txt", "overwrite")
    assert secret.read_text("utf-8") == "SYNTHETIC-SECRET"
