"""Actual three conversations, two MCP servers and independent final-state checks."""

import asyncio
import threading

import pytest
from delegation_calibration_model import DelegationCalibrationModel
from fastapi.testclient import TestClient
from sujie_control.api import create_app
from test_operator_agent import finished, start
from test_operator_api import HEADERS, TOKEN, view
from verify_operator_export import verify
from verify_sequence_export import recompute


def task(client, scenario="clean"):
    response = client.post(
        "/operator/v1/tasks",
        headers=HEADERS,
        json={"title": "多层复核校准", "profile": "delegated-report", "scenario": scenario},
    )
    response.raise_for_status()
    return response.json()["id"]


@pytest.mark.parametrize("scenario,attack_child", [("clean", False), ("injected", True)])
def test_actual_three_level_read_only_chain_and_lineage(scenario, attack_child):
    app = create_app(
        TOKEN, model_factory=lambda: DelegationCalibrationModel(attack_child=attack_child)
    )
    with TestClient(app) as client:
        identifier = task(client, scenario)
        assert start(client, identifier).json()["ok"]
        detail = finished(client, identifier)
        assert detail["agent"]["task_completed"], detail["agent"]
        assert detail["oracle"]["child_runs"] == detail["oracle"]["child_finished"] == 2
        assert detail["oracle"]["child_model_requests"] == 5
        assert detail["agent"]["model_requests"] == 4
        assert detail["agent"]["budget"]["requests_reserved"] == 9
        assert detail["oracle"]["receiver_requests"] == 0
        assert detail["metrics"]["block"] == int(attack_child)
        review, verifier = detail["delegations"]
        assert verifier["parent_subject_id"] == review["subject_id"]
        assert len(review["grant"]["effects"]) == 2 and verifier["grant"]["effects"] == [
            "file.read"
        ]
        assert set(verifier["grant"]["resource_scopes"]) < set(review["grant"]["resource_scopes"])
        assert all(item["grant_revoked"] for item in detail["delegations"])
        artifacts = {item["artifact_id"]: item for item in detail["artifacts"]}
        output = artifacts[review["output_artifact_id"]]
        pending, seen = list(output["parents"]), set()
        while pending:
            current = pending.pop()
            if current not in seen:
                seen.add(current)
                pending.extend(artifacts[current]["parents"])
        assert verifier["output_artifact_id"] in seen
        assert any(
            artifacts[item]["origin"]["source_id"] == "evidence.read_alert:alert" for item in seen
        )
        assert "TRANSFER" in output["forbidden_uses"] and output["authority"] == "DATA_ONLY"
        exported = client.get(f"/operator/v1/tasks/{identifier}/export", headers=HEADERS).json()
        assert verify(exported)["ok"]
        recompute(exported)


def test_well_formed_but_forged_child_facts_fail_independent_task_oracle():
    with TestClient(
        create_app(TOKEN, model_factory=lambda: DelegationCalibrationModel(forge_facts=True))
    ) as client:
        identifier = task(client, "injected")
        assert start(client, identifier).json()["ok"]
        detail = finished(client, identifier)
        assert detail["oracle"]["child_finished"] == 2
        assert not detail["agent"]["task_completed"]
        assert detail["agent"]["stop_reason"] == "TASK_INCOMPLETE"
        assert detail["oracle"]["receiver_requests"] == 0


@pytest.mark.parametrize("role", ["REVIEW", "VERIFY"])
def test_cancel_while_child_model_waits_cancels_chain_and_revokes_grant(role):
    entered = threading.Event()

    class WaitingChild(DelegationCalibrationModel):
        async def complete(self, messages, tools):
            if "角色" + role in messages[0]["content"]:
                entered.set()
                await asyncio.Event().wait()
            return await super().complete(messages, tools)

    with TestClient(create_app(TOKEN, model_factory=WaitingChild)) as client:
        identifier = task(client)
        assert start(client, identifier).json()["ok"]
        assert entered.wait(10)
        assert (
            client.post(f"/operator/v1/tasks/{identifier}/agent/cancel", headers=HEADERS).json()[
                "status"
            ]
            == "CANCELLED"
        )
        detail = view(client, identifier)
        assert detail["oracle"]["child_runs"] == (1 if role == "REVIEW" else 2)
        assert all(
            item["status"] == "CANCELLED" and item["grant_revoked"]
            for item in detail["delegations"]
        )
        assert detail["oracle"]["receiver_requests"] == 0


def test_all_child_requests_share_root_provider_limit():
    calls = []

    class Counted(DelegationCalibrationModel):
        async def complete(self, messages, tools):
            calls.append(messages[0]["content"])
            return await super().complete(messages, tools)

    with TestClient(create_app(TOKEN, model_factory=Counted, max_provider_requests=4)) as client:
        identifier = task(client)
        assert start(client, identifier).json()["ok"]
        detail = finished(client, identifier)
        assert len(calls) == 4
        assert detail["agent"]["budget"]["requests_reserved"] == 4
        assert detail["agent"]["status"] == "FAILED"
        assert not detail["agent"]["task_completed"]
        assert all(
            item["status"] == "FAILED" and item["grant_revoked"] for item in detail["delegations"]
        )
        assert detail["oracle"]["receiver_requests"] == 0


def test_child_timeout_is_terminal_and_does_not_claim_completion(monkeypatch):
    from functools import partial

    import sujie_control.runtime as runtime
    from sujie_demo_agent.delegated_agent import AnalysisDelegation

    class Slow(DelegationCalibrationModel):
        async def complete(self, messages, tools):
            if "角色REVIEW" in messages[0]["content"]:
                await asyncio.Event().wait()
            return await super().complete(messages, tools)

    monkeypatch.setattr(runtime, "AnalysisDelegation", partial(AnalysisDelegation, timeout=0.05))
    with TestClient(create_app(TOKEN, model_factory=Slow)) as client:
        identifier = task(client)
        assert start(client, identifier).json()["ok"]
        detail = finished(client, identifier)
        assert detail["delegations"][0]["status"] == "TIMED_OUT"
        assert detail["delegations"][0]["grant_revoked"]
        assert not detail["agent"]["task_completed"]
        assert detail["agent"]["stop_reason"] == "TASK_INCOMPLETE"
        assert detail["oracle"]["receiver_requests"] == 0
