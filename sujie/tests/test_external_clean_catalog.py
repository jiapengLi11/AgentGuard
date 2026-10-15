"""The independent clean catalog reader must parse data without importing TS."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))
from run_external_clean_catalog import load_descriptions  # noqa: E402


def test_concatenated_tool_description_and_source_identity(tmp_path):
    for relative in ("src/filesystem/server.ts", "src/memory/index.ts"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True)
        path.write_text(
            'throw new Error("must never run");\n'
            'server.registerTool("read_file", {title: "Read File", '
            'description: "Read text. " + "Use this tool when useful.", '
            "inputSchema: {}}, handler);\n",
            "utf-8",
        )
    rows, digest = load_descriptions(tmp_path)
    assert len(rows) == 2
    assert all(row["description"] == "Read text. Use this tool when useful." for row in rows)
    assert len(digest) == 64


def test_dynamic_description_fails_closed(tmp_path):
    for relative in ("src/filesystem/server.ts", "src/memory/index.ts"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True)
        path.write_text(
            'server.registerTool("read_file", {title: "Read File", '
            "description: computeDescription(), inputSchema: {}}, handler);\n",
            "utf-8",
        )
    with pytest.raises(ValueError, match="UNSUPPORTED_TOOL_DESCRIPTION"):
        load_descriptions(tmp_path)
