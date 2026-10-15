"""An autonomous Host pauses real MCP effects until its bound approval commits."""

import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sujie_control.api import create_app
from test_operator_agent import call, finished, start
from test_operator_api import HEADERS, TOKEN, action, approve_call, create_task, view
from verify_operator_export import verify


def test_executor_lost_ack_after_effect_stops_without_a_second_send():
    app = create_app(TOKEN, model_factory=IOCModel)
    with TestClient(app) as client:
        identifier = create_task(client, "ioc-transfer")
        assert start(client, identifier).json()["ok"]
        pending = waiting(client, identifier)["approvals"][-1]
        assert approve_call(client, identifier, pending, "approve").json()["ok"]
        session = app.state.manager.get(identifier)
        original = session.proxy.invoke

        async def lost_ack(tool, arguments):
            data = await original(tool, arguments)
            if tool == "operations.send_data":
                raise RuntimeError("SYNTHETIC_LOST_ACK")
            return data

        session.proxy.invoke = lost_ack
        assert (
            approve_call(client, identifier, pending, "commit").json()["code"]
            == "TOOL_EXECUTION_FAILED"
        )
        complete = finished(client, identifier)
        assert complete["agent"]["status"] == "FAILED"
        assert complete["agent"]["stop_reason"] == "EXECUTION_RESULT_UNKNOWN"
        assert complete["agent"]["model_requests"] == 2
        assert complete["oracle"]["receiver_requests"] == 1
        assert complete["approvals"][-1]["status"] == "FAILED"


def test_host_corrects_premature_completion_once_without_expanding_permissions():
    class PrematureModel(IOCModel):
        async def complete(self, messages, tools):
            if self.calls == 1:
                self.calls += 1
                return {"content": "已经完成通报", "tool_calls": []}
            if self.calls == 2 and not getattr(self, "corrected", False):
                self.calls = 1
                self.corrected = True
            return await super().complete(messages, tools)

    with TestClient(create_app(TOKEN, model_factory=PrematureModel)) as client:
        identifier = create_task(client, "ioc-transfer")
        before = view(client, identifier)
        assert start(client, identifier).json()["ok"]
        pending = waiting(client, identifier)["approvals"][-1]
        assert view(client, identifier)["oracle"]["receiver_requests"] == 0
        assert approve_call(client, identifier, pending, "approve").json()["ok"]
        assert approve_call(client, identifier, pending, "commit").json()["ok"]
        complete = finished(client, identifier)
        assert complete["agent"]["completion_reminders"] == 1
        assert complete["agent"]["task_completed"]
        assert complete["oracle"]["receiver_requests"] == 1
        assert complete["contract"] == before["contract"]
        assert complete["grant"] == before["grant"]


def test_persistent_false_completion_stops_after_one_reminder_without_send():
    class NoEffectModel:
        async def complete(self, messages, tools):
            return {"content": "声称已发送但没有实际动作", "tool_calls": []}

    with TestClient(create_app(TOKEN, model_factory=NoEffectModel)) as client:
        identifier = create_task(client, "ioc-transfer")
        assert start(client, identifier).json()["ok"]
        complete = finished(client, identifier)
        assert complete["agent"]["stop_reason"] == "TASK_INCOMPLETE"
        assert complete["agent"]["completion_reminders"] == 1
        assert complete["agent"]["model_requests"] == 2
        assert complete["oracle"]["receiver_requests"] == 0
        assert not complete["agent"]["task_completed"]


class IOCModel:
    """Scripted calibration, not an LLM evaluation or automatic approver."""

    def __init__(self):
        self.calls = 0
        self.usage = []

    async def complete(self, messages, tools):
        self.calls += 1
        self.usage.append({"total_tokens": 120})
        if self.calls == 1:
            return {"tool_calls": [call("read", "evidence__read_alert", {"alert_id": "alert"})]}
        if self.calls == 2:
            text = next(
                m["content"].split("content逐字等于：", 1)[1]
                for m in messages
                if m.get("role") == "system" and "content逐字等于：" in m.get("content", "")
            )
            return {
                "tool_calls": [
                    call(
                        "send",
                        "operations__send_data",
                        {"destination": "receiver", "content": text},
                    )
                ]
            }
        last_result = next(m["content"] for m in reversed(messages) if m["role"] == "tool")
        if self.calls == 3 and '"ok": false' in last_result:
            return {
                "tool_calls": [
                    call(
                        "report",
                        "operations__write_file",
                        {
                            "resource": "case-001/output/report.txt",
                            "content": "8.8.8.8、1.1.1.1 已核查；审批未通过，未发送。",
                        },
                    )
                ]
            }
        return {"content": "实际工具结果已确认，任务结束。", "tool_calls": []}


def waiting(client, identifier):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = view(client, identifier)
        if result["agent"]["status"] == "WAITING_APPROVAL":
            return result
        assert result["agent"]["status"] in {"RUNNING", "RESUMING"}, result["agent"]
        time.sleep(0.01)
    raise AssertionError("APPROVAL_WAIT_NOT_REACHED")


def test_autonomous_ask_stays_pending_then_single_commit_resumes_host():
    models = []

    def factory():
        model = IOCModel()
        models.append(model)
        return model

    with TestClient(create_app(TOKEN, model_factory=factory)) as client:
        identifier = create_task(client, "ioc-transfer")
        assert start(client, identifier).json()["ok"]
        paused = waiting(client, identifier)
        pending = paused["approvals"][-1]
        assert pending["status"] == "PENDING"
        assert paused["oracle"]["receiver_requests"] == 0
        assert models[0].calls == 2
        assert paused["agent"]["waiting_decision_id"] == pending["decision_id"]
        assert (
            action(client, identifier, "probe_private").json()["detail"]
            == "AGENT_RUN_LOCKS_MUTATIONS"
        )
        assert (
            approve_call(client, identifier, pending, "commit").json()["code"]
            == "APPROVAL_REQUIRED"
        )
        assert (
            approve_call(
                client, identifier, {**pending, "review_hash": "sha256:" + "0" * 64}, "approve"
            ).status_code
            == 409
        )
        assert (
            approve_call(
                client, identifier, pending, "approve", arguments={"content": "tamper"}
            ).status_code
            == 422
        )
        other = create_task(client, "ioc-transfer")
        assert approve_call(client, other, pending, "approve").status_code == 404
        assert approve_call(client, identifier, pending, "approve").json()["ok"]
        assert models[0].calls == 2  # Approval alone does not execute or resume.
        assert view(client, identifier)["oracle"]["receiver_requests"] == 0
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(lambda _: approve_call(client, identifier, pending, "commit"), range(2))
            )
        assert any(result.status_code == 200 and result.json().get("ok") for result in outcomes)
        complete = finished(client, identifier)
        assert complete["agent"]["status"] == "FINISHED"
        assert complete["agent"]["task_completed"]
        assert complete["oracle"]["receiver_requests"] == 1
        assert not complete["oracle"]["honeytoken_leaked"]
        assert complete["approvals"][-1]["status"] == "CONSUMED"
        assert models[0].calls == 3
        exported = client.get(f"/operator/v1/tasks/{identifier}/export", headers=HEADERS).json()
        assert exported["payload"]["mode"] == "sealed-local-model-ioc-transfer"
        assert verify(exported)["ok"]


def test_rejection_resumes_legal_report_without_sending():
    with TestClient(create_app(TOKEN, model_factory=IOCModel)) as client:
        identifier = create_task(client, "ioc-transfer")
        assert start(client, identifier).json()["ok"]
        pending = waiting(client, identifier)["approvals"][-1]
        assert approve_call(client, identifier, pending, "reject").json()["status"] == "REJECTED"
        complete = finished(client, identifier)
        assert complete["agent"]["status"] == "FINISHED"
        assert not complete["agent"]["task_completed"]  # Intended transfer was not performed.
        assert complete["oracle"]["report_written"]
        assert complete["oracle"]["receiver_requests"] == 0
        assert complete["approvals"][-1]["status"] == "REJECTED"


def test_approval_wait_timeout_keeps_receiver_empty_and_allows_fallback():
    with TestClient(create_app(TOKEN, model_factory=IOCModel, approval_timeout=0.05)) as client:
        identifier = create_task(client, "ioc-transfer")
        assert start(client, identifier).json()["ok"]
        complete = finished(client, identifier)
        assert complete["agent"]["status"] == "FINISHED"
        assert complete["oracle"]["receiver_requests"] == 0
        assert complete["oracle"]["report_written"]
        assert complete["approvals"][-1]["status"] == "REJECTED"


def test_cancellation_while_approved_but_uncommitted_prevents_late_effect():
    with TestClient(create_app(TOKEN, model_factory=IOCModel)) as client:
        identifier = create_task(client, "ioc-transfer")
        assert start(client, identifier).json()["ok"]
        pending = waiting(client, identifier)["approvals"][-1]
        assert approve_call(client, identifier, pending, "approve").json()["ok"]
        assert (
            client.post(f"/operator/v1/tasks/{identifier}/agent/cancel", headers=HEADERS).json()[
                "status"
            ]
            == "CANCELLED"
        )
        complete = view(client, identifier)
        assert complete["oracle"]["receiver_requests"] == 0
        assert complete["approvals"][-1]["status"] == "REJECTED"
        assert (
            approve_call(client, identifier, pending, "commit").json()["detail"]
            == "MODEL_TASK_LOCKS_MUTATIONS"
        )
        assert not client.get("/operator/v1/session", headers=HEADERS).json()["model"]["active"]


def test_parameter_drift_after_review_prevents_effect_and_resumes_failure_result():
    app = create_app(TOKEN, model_factory=IOCModel)
    with TestClient(app) as client:
        identifier = create_task(client, "ioc-transfer")
        assert start(client, identifier).json()["ok"]
        pending = waiting(client, identifier)["approvals"][-1]
        assert approve_call(client, identifier, pending, "approve").json()["ok"]
        # Deliberate trusted-Host fault, not a model/API mutation capability.
        app.state.manager.get(identifier).gateway._pending[
            pending["decision_id"]
        ].arguments_json = '{"destination":"receiver","content":"altered"}'
        assert (
            approve_call(client, identifier, pending, "commit").json()["code"] == "APPROVAL_STALE"
        )
        complete = finished(client, identifier)
        assert complete["oracle"]["receiver_requests"] == 0
        assert complete["oracle"]["report_written"]
        assert complete["approvals"][-1]["status"] == "REJECTED"


def test_model_cannot_repeat_same_rejected_action_to_generate_another_approval():
    class RepeatingIOCModel(IOCModel):
        async def complete(self, messages, tools):
            if self.calls == 2:
                self.calls = 1  # Deliberately retry the same second-round proposal.
            return await super().complete(messages, tools)

    with TestClient(create_app(TOKEN, model_factory=RepeatingIOCModel)) as client:
        identifier = create_task(client, "ioc-transfer")
        assert start(client, identifier).json()["ok"]
        pending = waiting(client, identifier)["approvals"][-1]
        assert approve_call(client, identifier, pending, "reject").json()["ok"]
        complete = finished(client, identifier)
        assert complete["agent"]["stop_reason"] == "REPEATED_BLOCKED_ACTION"
        assert len(complete["approvals"]) == 1
        assert complete["oracle"]["receiver_requests"] == 0
        assert any(
            event["details"].get("reason") == "DECLINED_ACTION_REPEATED"
            for event in complete["events"]
        )
