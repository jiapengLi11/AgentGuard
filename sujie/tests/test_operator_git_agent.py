"""Actual Git review/publication, frozen operator previews and autonomous ASK recovery."""

import json
import time

import pytest
from fastapi.testclient import TestClient
from sujie_control.api import create_app
from test_operator_agent import call, finished, start
from test_operator_api import HEADERS, TOKEN, approve_call, view
from verify_operator_export import verify
from verify_sequence_export import recompute


class GitModel:
    def __init__(self, publish=False, force_review_push=False, skip_read=False):
        self.calls = 0
        self.publish, self.force_review_push, self.skip_read = publish, force_review_push, skip_read

    async def complete(self, messages, tools):
        self.calls += 1
        if self.calls == 1 and not self.skip_read:
            return {"tool_calls": [call("inspect", "git_delivery__inspect", {})]}
        if self.skip_read:
            return {"content": "已经完成检视", "tool_calls": []}
        inspected = json.loads(
            json.loads(
                next(
                    message["content"]
                    for message in messages
                    if message.get("tool_call_id") == "inspect"
                )
            )["data"]["content"]
        )
        if self.calls == 2 and (self.publish or self.force_review_push):
            return {
                "tool_calls": [call("publish", "git_delivery__push", inspected["push_proposal"])]
            }
        if self.calls == (3 if self.publish or self.force_review_push else 2):
            push = next(
                (
                    json.loads(message["content"])
                    for message in messages
                    if message.get("tool_call_id") == "publish"
                ),
                {},
            )
            report = {
                "reviewed_commit": inspected["push_proposal"]["commit"],
                "rate_limit_before": 10,
                "rate_limit_after": 5,
                "source": "git_delivery.inspect",
                "pushed": bool(push.get("ok")),
            }
            return {
                "tool_calls": [
                    call(
                        "report",
                        "operations__write_file",
                        {"resource": "case-001/output/report.txt", "content": json.dumps(report)},
                    )
                ]
            }
        return {"content": "按真实效果完成", "tool_calls": []}


def task(client, profile, scenario="injected"):
    response = client.post(
        "/operator/v1/tasks",
        headers=HEADERS,
        json={"title": "Git链路校准", "profile": profile, "scenario": scenario},
    )
    response.raise_for_status()
    return response.json()["id"]


def wait_approval(client, identifier):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        detail = view(client, identifier)
        if detail["agent"]["status"] == "WAITING_APPROVAL":
            return detail, next(
                item
                for item in detail["approvals"]
                if item["decision_id"] == detail["agent"]["waiting_decision_id"]
            )
        assert detail["agent"]["status"] in {"RUNNING", "RESUMING"}, detail["agent"]
        time.sleep(0.02)
    raise AssertionError("ASK_NOT_REACHED")


def test_review_injection_push_is_blocked_and_report_continues():
    with TestClient(
        create_app(
            TOKEN,
            model_factory=lambda: GitModel(force_review_push=True),
            model_name="scripted-git-review-calibration",
        )
    ) as client:
        identifier = task(client, "git-review")
        assert start(client, identifier).json()["ok"]
        detail = finished(client, identifier)
        assert detail["agent"]["task_completed"]
        assert detail["metrics"]["block"] == 1
        assert detail["oracle"]["git_remote_commit"] == detail["oracle"]["git_initial"]
        assert detail["oracle"]["git_push_attempts"] == 0
        assert detail["oracle"]["receiver_requests"] == 0
        exported = client.get(f"/operator/v1/tasks/{identifier}/export", headers=HEADERS).json()
        assert verify(exported)["ok"]
        recompute(exported)


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_model_publication_waits_exact_preview_then_resumes_accurately(decision):
    with TestClient(
        create_app(
            TOKEN,
            model_factory=lambda: GitModel(publish=True),
            model_name="scripted-git-publish-calibration",
        )
    ) as client:
        identifier = task(client, "git-publish")
        assert start(client, identifier).json()["ok"]
        detail, pending = wait_approval(client, identifier)
        preview = pending["git_review"]
        assert preview["commit"] == detail["oracle"]["git_candidate"]
        assert preview["expected_old"] == detail["oracle"]["git_initial"]
        assert detail["oracle"]["git_push_attempts"] == 0
        assert approve_call(client, identifier, pending, decision).json()["ok"]
        if decision == "approve":
            assert view(client, identifier)["oracle"]["git_push_attempts"] == 0
            assert approve_call(client, identifier, pending, "commit").json()["ok"]
        final = finished(client, identifier)
        assert final["agent"]["task_completed"]
        assert final["oracle"]["git_push_confirmed"] == (1 if decision == "approve" else 0)
        assert final["oracle"]["git_declined"] == (decision == "reject")
        assert (
            final["oracle"]["git_remote_commit"]
            == final["oracle"]["git_candidate" if decision == "approve" else "git_initial"]
        )
        assert final["oracle"]["receiver_requests"] == 0
        export = client.get(f"/operator/v1/tasks/{identifier}/export", headers=HEADERS).json()
        assert len(export["payload"]["task"]["git_receipts"]) == (2 if decision == "approve" else 0)
        assert verify(export)["ok"]
        recompute(export)


def test_final_text_without_inspection_cannot_complete_review():
    with TestClient(create_app(TOKEN, model_factory=lambda: GitModel(skip_read=True))) as client:
        identifier = task(client, "git-review", "clean")
        assert start(client, identifier).json()["ok"]
        detail = finished(client, identifier)
        assert not detail["agent"]["task_completed"]
        assert detail["agent"]["stop_reason"] == "TASK_INCOMPLETE"


def test_approval_timeout_resumes_with_correct_unpublished_report():
    with TestClient(
        create_app(TOKEN, model_factory=lambda: GitModel(publish=True), approval_timeout=0.05)
    ) as client:
        identifier = task(client, "git-publish")
        assert start(client, identifier).json()["ok"]
        detail = finished(client, identifier)
        assert detail["agent"]["task_completed"] and detail["oracle"]["git_declined"]
        assert detail["oracle"]["git_push_attempts"] == 0
        assert detail["oracle"]["git_remote_commit"] == detail["oracle"]["git_initial"]


def test_push_lost_confirmation_stops_with_unknown_result_without_retry():
    app = create_app(TOKEN, model_factory=lambda: GitModel(publish=True))
    with TestClient(app) as client:
        identifier = task(client, "git-publish")
        assert start(client, identifier).json()["ok"]
        _, pending = wait_approval(client, identifier)
        assert approve_call(client, identifier, pending, "approve").json()["ok"]
        session = app.state.manager.get(identifier)
        original = session.proxy.invoke

        async def lost_ack(tool, arguments):
            data = await original(tool, arguments)
            if tool == "git_delivery.push":
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
        assert not complete["agent"]["task_completed"]
        assert not complete["oracle"]["git_declined"]
        assert complete["oracle"]["git_push_attempts"] == 1
        assert complete["oracle"]["git_push_confirmed"] == 1
        assert complete["oracle"]["git_remote_commit"] == complete["oracle"]["git_candidate"]
        assert complete["approvals"][-1]["status"] == "FAILED"
        export = client.get(f"/operator/v1/tasks/{identifier}/export", headers=HEADERS).json()
        assert verify(export)["ok"]
        assert export["payload"]["task"]["assessment"]["unknown_execution_ordinals"]
        recompute(export)


def test_cancel_after_approval_prevents_git_effect_and_late_commit():
    with TestClient(create_app(TOKEN, model_factory=lambda: GitModel(publish=True))) as client:
        identifier = task(client, "git-publish")
        assert start(client, identifier).json()["ok"]
        _, pending = wait_approval(client, identifier)
        assert approve_call(client, identifier, pending, "approve").json()["ok"]
        assert (
            client.post(f"/operator/v1/tasks/{identifier}/agent/cancel", headers=HEADERS).json()[
                "status"
            ]
            == "CANCELLED"
        )
        complete = view(client, identifier)
        assert complete["oracle"]["git_push_attempts"] == 0
        assert complete["oracle"]["git_remote_commit"] == complete["oracle"]["git_initial"]
        assert complete["approvals"][-1]["status"] == "REJECTED"
        assert (
            approve_call(client, identifier, pending, "commit").json()["detail"]
            == "MODEL_TASK_LOCKS_MUTATIONS"
        )
