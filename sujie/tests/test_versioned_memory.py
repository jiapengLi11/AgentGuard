"""Actual SQLite history, CAS races and an executor bypass calibration."""

import sqlite3
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import pytest
from mcp import StdioServerParameters
from sujie_control.profiles import records
from sujie_gateway.m1_runtime import LOCAL_TOOL_CATALOG, M1Gateway, StdioMCPProxy
from sujie_gateway.memory_policy import MemoryError, MemoryPolicy, content_hash
from versioned_memory import VersionedMemory, initialize

ROOT = Path(__file__).resolve().parents[1]
OLD, NEW = '{"owner":"blue"}', '{"owner":"green"}'


def policy(initial=0, write=1):
    return MemoryPolicy.from_dict(
        {
            "namespace": "test-range",
            "key": "asset-note",
            "initial_revision": initial,
            "versions": {
                str(n): content_hash((OLD, NEW)[n - 1]) for n in range(1, (write or initial) + 1)
            },
            "write_revision": write,
            "max_bytes": 1024,
        }
    )


def arguments(revision=0):
    return {
        "key": "asset-note",
        "content": NEW if revision else OLD,
        "expected_revision": revision,
        "expected_hash": content_hash(OLD) if revision else "",
    }


def seeded(tmp_path, updated=False):
    database, receipts = tmp_path / "memory.sqlite3", tmp_path / "receipts.jsonl"
    initialize(database)
    VersionedMemory(database, policy(), receipts).write(arguments())
    store = VersionedMemory(database, policy(1, 2), receipts)
    if updated:
        store.write(arguments(1))
    return database, receipts, store


def test_restart_update_preserves_history_and_rejects_replayed_old_revision(tmp_path):
    database, receipts, store = seeded(tmp_path)
    assert store.read({"key": "asset-note"})["content"] == OLD
    store.write(arguments(1))
    assert store.read({"key": "asset-note"})["content"] == NEW
    with pytest.raises(MemoryError, match="MEMORY_CAS_CONFLICT"):
        store.write(arguments(1))
    reopened = VersionedMemory(database, policy(2, None), receipts)
    assert reopened.read({"key": "asset-note"})["revision"] == 2
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT content FROM evidence_memory ORDER BY revision").fetchall() == [
            (OLD,),
            (NEW,),
        ]


@pytest.mark.parametrize(
    "tamper", ["content", "content-and-hash", "rollback", "old-revision", "oversized"]
)
def test_storage_tamper_cannot_be_laundered_as_new_evidence(tmp_path, tamper):
    database, _, store = seeded(tmp_path, True)
    with closing(sqlite3.connect(database)) as db, db:
        if tamper == "rollback":
            db.execute("DELETE FROM evidence_memory WHERE revision=2")
        elif tamper == "old-revision":
            db.execute("UPDATE evidence_memory SET revision=3 WHERE revision=1")
        else:
            text = "X" * 1025 if tamper == "oversized" else '{"owner":"red"}'
            if tamper == "content-and-hash":
                db.execute(
                    "UPDATE evidence_memory SET content=?,content_hash=? WHERE revision=1",
                    (text, content_hash(text)),
                )
            else:
                db.execute("UPDATE evidence_memory SET content=? WHERE revision=1", (text,))
    with pytest.raises(MemoryError, match="MEMORY_(?:HISTORY|CONTENT)_CHANGED"):
        store.read({"key": "asset-note"})


def test_two_writer_cas_conflict_has_exactly_one_new_revision(tmp_path):
    database, receipts, _ = seeded(tmp_path)
    stores = [VersionedMemory(database, policy(1, 2), receipts) for _ in range(2)]

    def write(store):
        try:
            return store.write(arguments(1))["revision"]
        except MemoryError:
            return "refused"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(write, stores))
    assert sorted(map(str, results)) == ["2", "refused"]
    assert len(receipts.read_text("utf-8").splitlines()) == 2


def test_same_instance_read_returns_a_coherent_revision_and_body(tmp_path, monkeypatch):
    _, _, store = seeded(tmp_path)
    read_closed, written = threading.Event(), threading.Event()
    original = store.connect

    class ReadConnection:
        def __init__(self, db):
            self.db = db

        def execute(self, *args):
            return self.db.execute(*args)

        def close(self):
            self.db.close()
            read_closed.set()
            written.wait(0.3)

    def connect():
        db = original()
        return ReadConnection(db) if threading.current_thread().name.endswith("_0") else db

    def update():
        result = store.write(arguments(1))
        written.set()
        return result

    monkeypatch.setattr(store, "connect", connect)
    with ThreadPoolExecutor(2, thread_name_prefix="memory-snapshot") as pool:
        read = pool.submit(store.read, {"key": "asset-note"})
        assert read_closed.wait(3)
        write = pool.submit(update)
        observed = read.result(timeout=3)
        assert write.result(timeout=3)["revision"] == 2
    assert observed["revision"] == (1 if observed["content"] == OLD else 2)
    assert observed["content_sha256"] == content_hash(observed["content"])


@pytest.mark.asyncio
async def test_gateway_requires_actual_source_and_mcp_still_rejects_forged_content(tmp_path):
    database, receipts = tmp_path / "memory.sqlite3", tmp_path / "receipts.jsonl"
    initialize(database)
    config = tmp_path / "policy.json"
    config.write_text(policy().wire_json, "utf-8")
    params = {
        "memory": StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "mcp-servers/versioned-memory-server/server.py")],
            env={
                "SUJIE_MEMORY_DB": str(database),
                "SUJIE_MEMORY_POLICY": str(config),
                "SUJIE_MEMORY_RECEIPTS": str(receipts),
            },
        )
    }
    async with StdioMCPProxy(
        params, expected_tools={"memory": LOCAL_TOOL_CATALOG["memory"]}
    ) as proxy:
        contract, grant = records("memory-update")
        with pytest.raises(ValueError, match="MEMORY_POLICY_BINDING_INVALID"):
            M1Gateway(proxy, contract, grant)
        gateway = M1Gateway(proxy, contract, grant, memory_policy=policy())
        assert (await gateway.call("memory.write", arguments()))[
            "code"
        ] == "MEMORY_SOURCE_UNREGISTERED"
        for changed in (
            arguments() | {"key": "other"},
            arguments() | {"expected_revision": 1},
            arguments() | {"content": "forged"},
        ):
            assert (await gateway.call("memory.write", changed))["decision"] == "BLOCK"
            with pytest.raises(RuntimeError, match="MCP_TOOL_ERROR"):
                await proxy.invoke("memory.write", changed)
        event = gateway.trace.emit("CONTENT_REGISTERED", actor_id=grant.to_dict()["subject_id"])
        secret = gateway.trace.create_artifact(
            OLD, source_event_id=event, source_id="owned-secret", confidentiality="SECRET"
        )
        gateway._exposed_artifacts.add(secret)
        assert (await gateway.call("memory.write", arguments()))[
            "code"
        ] == "MEMORY_SOURCE_UNREGISTERED"
        source = gateway.trace.create_artifact(
            OLD, source_event_id=event, source_id="owned-calibration-source"
        )
        gateway._exposed_artifacts.add(source)
        written = await gateway.call("memory.write", arguments())
        assert written["ok"]
        assert (
            VersionedMemory(database, policy(1, None), receipts).read({"key": "asset-note"})[
                "content"
            ]
            == OLD
        )
        assert len(receipts.read_text("utf-8").splitlines()) == 1
