"""Owned SQLite evidence memory with bounded reads, pinned history and atomic CAS."""

import json
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from sujie_gateway.memory_policy import MemoryError, MemoryPolicy, content_hash


def initialize(path: Path):
    if path.exists():
        raise MemoryError("MEMORY_DATABASE_ALREADY_EXISTS")
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "CREATE TABLE evidence_memory(namespace TEXT NOT NULL, key TEXT NOT NULL, revision INTEGER NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL, PRIMARY KEY(namespace,key,revision))"
        )


class VersionedMemory:
    def __init__(self, path: Path, policy: MemoryPolicy, receipts: Path):
        self.path, self.policy, self.receipts = path, policy, receipts
        self.revision = policy.to_dict()["initial_revision"]
        self._lock = threading.RLock()

    def connect(self):
        if not self.path.is_file():
            raise MemoryError("MEMORY_DATABASE_UNAVAILABLE")
        return sqlite3.connect(self.path, timeout=1)

    def _history(self, db):
        config = self.policy.to_dict()
        rows = db.execute(
            "SELECT key,revision,length(CAST(content AS BLOB)),content_hash FROM evidence_memory WHERE namespace=? ORDER BY revision LIMIT 10",
            (config["namespace"],),
        ).fetchall()
        if len(rows) != self.revision or any(
            key != config["key"]
            or revision != index
            or size > config["max_bytes"]
            or digest != config["versions"][str(index)]
            for index, (key, revision, size, digest) in enumerate(rows, 1)
        ):
            raise MemoryError("MEMORY_HISTORY_CHANGED")
        content = ""
        for _, revision, _, digest in rows:
            content = db.execute(
                "SELECT content FROM evidence_memory WHERE namespace=? AND key=? AND revision=?",
                (config["namespace"], config["key"], revision),
            ).fetchone()[0]
            if not isinstance(content, str) or content_hash(content) != digest:
                raise MemoryError("MEMORY_CONTENT_CHANGED")
        return content

    def read(self, arguments):
        with self._lock:
            return self._read(arguments)

    def _read(self, arguments):
        request = self.policy.inspect(False, arguments)
        if not request["permitted"]:
            raise MemoryError(request["operation"])
        try:
            with closing(self.connect()) as db:
                db.execute("BEGIN")
                content = self._history(db)
                if self.revision == 0:
                    raise MemoryError("MEMORY_NOT_FOUND")
        except sqlite3.Error:
            raise MemoryError("MEMORY_STORAGE_FAILED") from None
        return {
            "key": arguments["key"],
            "content": content,
            "revision": self.revision,
            "content_sha256": content_hash(content),
            "namespace": self.policy.to_dict()["namespace"],
        }

    def write(self, arguments):
        with self._lock:
            return self._write(arguments)

    def _write(self, arguments):
        request = self.policy.inspect(True, arguments)
        if not request["permitted"]:
            raise MemoryError(request["operation"])
        config = self.policy.to_dict()
        if self.revision != arguments["expected_revision"]:
            raise MemoryError("MEMORY_CAS_CONFLICT")
        revision, content = config["write_revision"], arguments["content"]
        try:
            with closing(self.connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                self._history(db)
                db.execute(
                    "INSERT INTO evidence_memory VALUES(?,?,?,?,?)",
                    (config["namespace"], config["key"], revision, content, content_hash(content)),
                )
        except sqlite3.Error:
            raise MemoryError("MEMORY_STORAGE_FAILED") from None
        self.revision = revision
        row = {
            "event": "MEMORY_COMMITTED",
            "namespace": config["namespace"],
            "key": config["key"],
            "revision": revision,
            "previous_revision": arguments["expected_revision"],
            "previous_hash": arguments["expected_hash"],
            "content_sha256": content_hash(content),
            "time_ns": time.time_ns(),
        }
        with self.receipts.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        return {
            "key": config["key"],
            "revision": revision,
            "content_sha256": content_hash(content),
            "bytes_written": len(content.encode()),
        }
