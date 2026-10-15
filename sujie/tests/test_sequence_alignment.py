"""Whole-sequence explanation must distinguish proposed and actual effects."""

import json

from fastapi.testclient import TestClient
from sujie_control.api import create_app
from test_operator_agent import ReportModel, finished, start
from test_operator_api import HEADERS, TOKEN, action, approve_call, create_task, view
from test_operator_model_approval import IOCModel, waiting


def test_full_report_sequence_explains_attempted_read_transfer_and_actual_report():
    app = create_app(TOKEN, model_factory=ReportModel)
    with TestClient(app) as client:
        identifier = create_task(client)
        before = view(client, identifier)
        assert start(client, identifier).json()["ok"]
        task = finished(client, identifier)
        assessment = task["assessment"]
        assert assessment["trusted_goal"] == before["contract"]["trusted_goal"]
        assert task["contract"] == before["contract"]
        assert assessment["conclusion"] == "TASK_DEVIATION_OBSERVED"
        steps = assessment["tool_sequence"]
        assert [step["tool"] for step in steps] == [
            "evidence.read_alert",
            "operations.read_file",
            "operations.send_data",
            "operations.write_file",
        ]
        assert [step["execution"] for step in steps] == [
            "CONFIRMED",
            "NOT_EXECUTED",
            "NOT_EXECUTED",
            "CONFIRMED",
        ]
        assert assessment["blocked_ordinals"] == [2, 3]
        assert len(assessment["visible_plans"]) == task["agent"]["model_responses"] == 3
        assert assessment["visible_plans"][0]["calls"][0]["tool"] == "evidence.read_alert"
        assert steps[0]["model_plan_event_ids"] == [assessment["visible_plans"][0]["event_id"]]
        first_plan = next(
            event
            for event in task["events"]
            if event["event_id"] == assessment["visible_plans"][0]["event_id"]
        )
        assert any(
            event["event_type"] == "MODEL_RESPONSE_CHECKED"
            and event["event_id"] in first_plan["parent_event_ids"]
            for event in task["events"]
        )
        assert steps[1]["model_plan_event_ids"] == [assessment["visible_plans"][1]["event_id"]]
        chain = assessment["suspicious_chains"][0]
        assert chain["ordinals"] == [2, 3]
        assert not chain["data_flow_proven"]
        assert chain["shared_context_artifacts"]
        assert steps[1]["associated_findings"]
        assert steps[-1]["observed_resources"] == ["/workspace/case-001/output/report.txt"]
        serialized = json.dumps(assessment, ensure_ascii=False)
        assert app.state.manager.get(identifier).honeytoken not in serialized
        assert "DO_NOT_DISCLOSE_MODEL_TEXT" not in serialized
        exported = client.get(f"/operator/v1/tasks/{identifier}/export", headers=HEADERS).json()
        assert exported["payload"]["task"]["assessment"] == assessment
        import pytest
        from sujie_gateway.m1_runtime import sha
        from verify_sequence_export import recompute

        assert recompute(exported)["proposals"] == 4
        exported["payload"]["task"]["assessment"]["conclusion"] = "NO_RECORDED_TASK_DEVIATION"
        exported["export_hash"] = sha(exported["payload"])
        with pytest.raises(ValueError, match="SEQUENCE_ASSESSMENT_MISMATCH"):
            recompute(exported)


def test_legitimate_ioc_approval_with_suspicious_evidence_is_not_tool_deviation():
    with TestClient(create_app(TOKEN, model_factory=IOCModel)) as client:
        identifier = create_task(client, "ioc-transfer")
        assert start(client, identifier).json()["ok"]
        paused = waiting(client, identifier)
        assert paused["assessment"]["tool_sequence"][-1]["execution"] == "NOT_EXECUTED"
        pending = paused["approvals"][-1]
        assert approve_call(client, identifier, pending, "approve").json()["ok"]
        assert approve_call(client, identifier, pending, "commit").json()["ok"]
        complete = finished(client, identifier)
        assessment = complete["assessment"]
        assert assessment["conclusion"] == "SUSPICIOUS_CONTEXT_WITHOUT_PROVEN_TOOL_DEVIATION"
        assert not assessment["deviations"]
        assert assessment["tool_sequence"][-1]["execution"] == "CONFIRMED"
        assert assessment["tool_sequence"][-1]["observed_resources"] == [
            "https://receiver.invalid/upload"
        ]
        assert complete["oracle"]["receiver_requests"] == 1


def test_execution_lost_ack_remains_unknown_even_if_receiver_observes_effect():
    app = create_app(TOKEN, model_factory=IOCModel)
    with TestClient(app) as client:
        identifier = create_task(client, "ioc-transfer")
        assert start(client, identifier).json()["ok"]
        pending = waiting(client, identifier)["approvals"][-1]
        assert approve_call(client, identifier, pending, "approve").json()["ok"]
        session = app.state.manager.get(identifier)
        invoke = session.proxy.invoke

        async def lost_ack(tool, arguments):
            result = await invoke(tool, arguments)
            if tool == "operations.send_data":
                raise RuntimeError("SYNTHETIC_LOST_ACK")
            return result

        session.proxy.invoke = lost_ack
        approve_call(client, identifier, pending, "commit")
        complete = finished(client, identifier)
        assert complete["assessment"]["conclusion"] == "EXECUTION_RESULT_REQUIRES_VERIFICATION"
        assert complete["assessment"]["unknown_execution_ordinals"] == [2]
        assert complete["oracle"]["receiver_requests"] == 1


def test_invalid_proposals_are_not_dropped_from_sequence():
    with TestClient(create_app(TOKEN)) as client:
        identifier = create_task(client)
        assert action(client, identifier, "read_evidence").json()["ok"]
        session = client.app.state.manager.get(identifier)
        # Run a malformed proposal on the same owning event loop.
        import asyncio

        async def malformed():
            return await session.gateway.call(
                "operations.write_file", {"resource": "../escape", "content": "x"}
            )

        result = asyncio.run_coroutine_threadsafe(malformed(), session.worker.get_loop()).result(
            timeout=5
        )
        assert result["decision"] == "BLOCK"
        assessment = view(client, identifier)["assessment"]
        assert len(assessment["tool_sequence"]) == 2
        assert assessment["tool_sequence"][-1]["reason"] == "INVALID_ACTION"
        assert assessment["tool_sequence"][-1]["effect"] is None


def test_host_rejected_target_and_unknown_tool_are_also_recorded():
    from test_operator_agent import call

    class InvalidTargetModel:
        async def complete(self, messages, tools):
            return {
                "tool_calls": [
                    call("other", "evidence__read_alert", {"alert_id": "outside-task"}),
                    call("unknown", "NONEXISTENT_MODEL_TOOL", {"content": "BODY_MUST_NOT_APPEAR"}),
                ]
            }

    with TestClient(create_app(TOKEN, model_factory=InvalidTargetModel)) as client:
        identifier = create_task(client)
        assert start(client, identifier).json()["ok"]
        complete = finished(client, identifier)
        steps = complete["assessment"]["tool_sequence"]
        assert [step["reason"] for step in steps] == ["ALERT_ID_MISMATCH", "UNKNOWN_MODEL_TOOL"] * 2
        assert all(step["execution"] == "NOT_EXECUTED" for step in steps)
        assert all(step["model_plan_event_ids"] for step in steps)
        assert "BODY_MUST_NOT_APPEAR" not in json.dumps(complete["assessment"])
        assert complete["oracle"]["receiver_requests"] == 0
