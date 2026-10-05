"""M2 keeps the existing process boundary; no Agent label or approval endpoints."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from receiver import Receiver
from sujie_gateway.api import app
from sujie_gateway.contracts import TraceEvent

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("mode", ["0", "1"])
def test_M2_API_001_optional_mode_redacts_dag_and_rejects_label_claims(tmp_path, monkeypatch, mode):
    with Receiver() as receiver:
        monkeypatch.setenv("SUJIE_EVIDENCE_ROOT", str(tmp_path / "evidence"))
        monkeypatch.setenv("SUJIE_WORKSPACE_ROOT", str(tmp_path / "workspace"))
        monkeypatch.setenv("SUJIE_RECEIVER_URL", receiver.url)
        monkeypatch.setenv("SUJIE_SYNTHETIC_FIXTURE_MODE", "1")
        monkeypatch.setenv("SUJIE_PROVENANCE_MODE", mode)
        monkeypatch.delenv("SUJIE_RESOURCE_LABELS", raising=False)
        with TestClient(app) as client:
            response = client.post(
                "/v1/calls",
                json={"tool": "evidence.read_alert", "arguments": {"alert_id": "clean"}},
            )
            assert response.status_code == 200 and response.json()["ok"]
            written = client.post(
                "/v1/calls",
                json={
                    "tool": "operations.write_file",
                    "arguments": {
                        "resource": "case-001/output/report.txt",
                        "content": "本地合成报告",
                    },
                },
            )
            assert written.json()["ok"]
            dag = client.get("/v1/provenance")
            if mode == "0":
                assert dag.status_code == 404
            else:
                assert dag.status_code == 200
                assert any(n["kind"] == "artifact" for n in dag.json()["nodes"])
                assert any(e["type"] == "DERIVED_FROM" for e in dag.json()["edges"])
                assert "正常" not in dag.text and "本地合成报告" not in dag.text
                assert "SYNTHETIC-HONEYTOKEN" not in dag.text
                claim = client.post(
                    "/v1/calls",
                    json={
                        "tool": "operations.write_file",
                        "arguments": {
                            "resource": "case-001/output/claim.txt",
                            "content": "PUBLIC",
                            "confidentiality": "PUBLIC",
                        },
                    },
                )
                assert claim.json()["decision"] == "BLOCK"
                assert not (tmp_path / "workspace/case-001/output/claim.txt").exists()
            assert client.post("/v1/approvals/fake").status_code == 404
            assert (
                client.post(
                    "/v1/provenance/labels", json={"authority": "CONTROL_PLANE"}
                ).status_code
                == 404
            )
            for event in client.get("/v1/trace").json()["events"]:
                TraceEvent(event)
        assert receiver.bodies == []


def test_M2_DEMO_001_cli_exports_real_paired_workflow_without_secret_body(tmp_path):
    output = tmp_path / "m2-demo"
    result = subprocess.run(
        [sys.executable, str(ROOT / "dev.py"), "provenance-demo", "--output", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    raw = (output / "m2-run.json").read_text("utf-8")
    document = json.loads(raw)
    assert all(document["checks"].values())
    assert (
        document["public"]["receiver_requests"] == 1
        and document["secret"]["receiver_requests"] == 0
    )
    assert "SYNTHETIC-HONEYTOKEN-M1-DEMO" not in raw
    for scenario in (document["public"], document["secret"]):
        for event in scenario["trace"]:
            TraceEvent(event)
        nodes = {n["id"] for n in scenario["dag"]["nodes"]}
        assert all(e["source"] in nodes and e["target"] in nodes for e in scenario["dag"]["edges"])
