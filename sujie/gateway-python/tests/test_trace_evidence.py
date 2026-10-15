import sqlite3
from pathlib import Path

import pytest
from sujie_gateway.contracts import ProvenanceEnvelope, TaskContract, TraceEvent
from sujie_gateway.m1_runtime import TraceLedger


def test_trace_evidence_is_linked_persisted_and_sanitized(tmp_path: Path, fixture_document):
    contract = TaskContract(fixture_document("task-contract"))
    database = tmp_path / "trace.sqlite3"
    ledger = TraceLedger(contract, database)
    assert ledger._db.execute("PRAGMA journal_mode").fetchone()[0] == "truncate"
    assert ledger._db.execute("PRAGMA synchronous").fetchone()[0] == 3
    executed = ledger.emit(
        "EXECUTION_RESULT",
        actor_id=contract.to_dict()["principal_id"],
        payload={"tool": "evidence.read_alert", "ok": True},
    )
    secret = "SYNTHETIC-PRIVATE-ALERT"
    artifact_id = ledger.create_artifact(
        secret,
        source_event_id=executed,
        source_id="evidence.read_alert:case-001",
    )
    ledger.store_normalized_view(artifact_id, "SYNTHETIC-PRIVATE-ALERT")
    exposed = ledger.emit(
        "MODEL_EXPOSED",
        actor_id=contract.to_dict()["principal_id"],
        parents=[executed],
        artifact_ids=[artifact_id],
        payload={"tool": "evidence.read_alert"},
    )

    assert database.is_file()
    assert ledger.payloads[executed]["ok"] is True
    assert ledger.artifact_contents[artifact_id] == secret
    assert ledger.normalized_views[artifact_id] == secret
    ProvenanceEnvelope(ledger.artifacts[artifact_id].to_dict())
    TraceEvent(ledger.events[-1])
    assert ledger.events[-1]["event_id"] == exposed
    assert secret not in str(ledger.dag())
    with pytest.raises(ValueError, match="UNKNOWN_TRACE_PARENT"):
        ledger.emit(
            "MODEL_EXPOSED",
            actor_id=contract.to_dict()["principal_id"],
            parents=[contract.to_dict()["principal_id"]],
        )

    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM trace_events").fetchone()[0] == 2
        assert db.execute("SELECT content FROM artifacts").fetchone()[0] == secret
        assert db.execute("SELECT content FROM normalized_views").fetchone()[0] == secret
    ledger.close()
    ledger.close()
    reopened = TraceLedger(contract, database)
    assert reopened.artifact_contents[artifact_id] == secret
    assert (
        reopened.artifacts[artifact_id].to_dict()["content_hash"]
        == ledger.artifacts[artifact_id].to_dict()["content_hash"]
    )
    assert reopened._db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    reopened.close()


def test_derived_artifact_inherits_strictest_parent_labels(fixture_document):
    contract = TaskContract(fixture_document("task-contract"))
    ledger = TraceLedger(contract)
    actor = contract.to_dict()["principal_id"]
    read = ledger.emit("EXECUTION_RESULT", actor_id=actor)
    internal = ledger.create_artifact(
        "INTERNAL-EVIDENCE-CONTENT",
        source_event_id=read,
        source_id="evidence:internal",
    )
    secret = ledger.create_artifact(
        "SYNTHETIC-SECRET-EVIDENCE",
        source_event_id=read,
        source_id="evidence:secret",
        confidentiality="SECRET",
    )
    with pytest.raises(ValueError, match="IOC_SOURCE_NOT_DECLASSIFIABLE"):
        ledger.public_ioc_content(secret)
    summarized = ledger.emit(
        "CONTENT_SUMMARIZED",
        actor_id=actor,
        parents=[read],
        artifact_ids=[internal, secret],
        payload={"transformation": "SUMMARY"},
    )
    child_id = ledger.create_derived_artifact(
        "derived content",
        source_event_id=summarized,
        source_id="trusted-host:model-output",
        parents=[internal, secret],
        transformation="SUMMARY",
    )
    child = ledger.artifacts[child_id].to_dict()
    assert child["confidentiality"] == "SECRET"
    assert child["authority"] == "DATA_ONLY"
    assert child["integrity"] == "UNTRUSTED"
    assert "TRANSFER" in child["forbidden_uses"]
    assert child["parents"] == sorted([internal, secret])
    assert child["source_spans"] == []
    assert "derived content" not in str(ledger.dag())
    with pytest.raises(ValueError, match="INVALID_DERIVATION"):
        ledger.create_derived_artifact(
            "orphan",
            source_event_id=summarized,
            source_id="trusted-host:model-output",
            parents=[],
            transformation="SUMMARY",
        )
