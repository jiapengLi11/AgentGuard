"""Synthetic persistent memory MCP server; authorization stays in the Gateway."""

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from mcp.server import MCPServer

DATABASE = Path(os.environ["SUJIE_MEMORY_DB"])
KEY = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
server = MCPServer("sujie-memory", version="0.1.0")


def connection() -> sqlite3.Connection:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE)
    db.execute("CREATE TABLE IF NOT EXISTS memory (key TEXT PRIMARY KEY, content TEXT NOT NULL)")
    return db


@server.tool(description="Store synthetic task evidence by a bounded key.", structured_output=True)
def write(key: str, content: str) -> dict[str, object]:
    if KEY.fullmatch(key) is None:
        raise ValueError("invalid memory key")
    with closing(connection()) as db:
        with db:
            db.execute("INSERT OR REPLACE INTO memory VALUES (?, ?)", (key, content))
    return {"key": key, "bytes_written": len(content.encode("utf-8"))}


@server.tool(description="Read synthetic task evidence by a bounded key.", structured_output=True)
def read(key: str) -> dict[str, str]:
    if KEY.fullmatch(key) is None:
        raise ValueError("invalid memory key")
    with closing(connection()) as db:
        row = db.execute("SELECT content FROM memory WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise ValueError("memory not found")
    return {"key": key, "content": row[0]}


if __name__ == "__main__":
    server.run("stdio")
