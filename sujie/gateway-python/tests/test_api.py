from fastapi.testclient import TestClient
from receiver import Receiver
from sujie_gateway.api import app
from sujie_gateway.contracts import TraceEvent


def test_M1_API_001_agent_only_gets_call_and_sanitized_trace(tmp_path, monkeypatch):
    evidence, workspace = tmp_path / "evidence", tmp_path / "workspace"
    with Receiver() as receiver:
        monkeypatch.setenv("SUJIE_EVIDENCE_ROOT", str(evidence))
        monkeypatch.setenv("SUJIE_WORKSPACE_ROOT", str(workspace))
        monkeypatch.setenv("SUJIE_RECEIVER_URL", receiver.url)
        monkeypatch.setenv("SUJIE_SYNTHETIC_FIXTURE_MODE", "1")
        with TestClient(app) as client:
            read = client.post(
                "/v1/calls",
                json={"tool": "evidence.read_alert", "arguments": {"alert_id": "clean"}},
            )
            assert read.status_code == 200
            assert read.json()["decision"] == "ALLOW"
            blocked = client.post(
                "/v1/calls",
                json={
                    "tool": "operations.read_file",
                    "arguments": {"resource": "case-001/secret.txt"},
                },
            )
            assert blocked.json()["decision"] == "BLOCK"
            assert client.post("/v1/approvals/not-exposed").status_code == 404
            assert client.post("/v1/host-content").status_code == 404
            trace = client.get("/v1/trace").json()["events"]
            for event in trace:
                TraceEvent(event)
            assert "SYNTHETIC-HONEYTOKEN" not in str(trace)
        assert receiver.bodies == []
