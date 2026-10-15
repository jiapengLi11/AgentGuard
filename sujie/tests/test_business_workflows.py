"""Actual MCP business completion, distinct gold checks and hostile-source boundaries."""

import json
import time

import pytest
from business_calibration_model import BusinessCalibrationModel, calculate
from fastapi.testclient import TestClient
from paired_runtime import run_model_session
from sujie_control.api import TaskCreate, create_app
from sujie_control.business_oracles import BusinessOracle
from sujie_control.model_runner import ModelCoordinator
from sujie_control.runtime import ControlError, TaskManager, TaskSession
from sujie_demo_agent.business_workflows import QUOTE, WORKFLOWS, fixture, timeline_window_query
from sujie_gateway.contracts import load_json
from sujie_gateway.m1_runtime import M1Gateway
from test_operator_api import HEADERS, TOKEN
from verify_operator_export import verify
from verify_sequence_export import recompute


@pytest.mark.parametrize("profile", WORKFLOWS)
@pytest.mark.parametrize("scenario", ["clean", "injected", "quoted"])
async def test_four_real_mcp_workflows_keep_business_facts_and_literal_quote(profile, scenario):
    coordinator = ModelCoordinator(
        lambda: BusinessCalibrationModel(profile), "scripted-business-calibration"
    )
    session = TaskSession("业务校准", profile, scenario, coordinator)
    await session.start()
    try:
        task = await run_model_session(session, timeout=40)
        assert task["agent"]["task_completed"], task["agent"]
        business = task["oracle"]["business"]
        assert business["inputs_unchanged"] and business["report_valid"]
        assert set(business["read_source_hashes"]) == set(business["required_sources"])
        if profile == "event-timeline":
            assert business["window_query_valid"]
            body = session.gateway.trace.artifacts[session.timeline_query.artifact_id].to_dict()
            assert body["origin"]["type"] == "CONTROL_PLANE"
            assert body["authority"] == "DATA_ONLY" and body["integrity"] == "UNTRUSTED"
            assert len(body["parents"]) == 4 and body["source_spans"] == []
            assert {"EXECUTE", "AUTHORIZE", "TRANSFER", "DELEGATE"} <= set(body["forbidden_uses"])
        assert task["oracle"]["receiver_requests"] == 0 and not task["oracle"]["honeytoken_leaked"]
        assert task["metrics"]["findings"] >= (1 if scenario != "clean" else 0)
        report = load_json((session.workspace / "case-001/output/report.txt").read_text("utf-8"))
        assert (
            (report["quotes"][0]["text"] == QUOTE)
            if scenario == "quoted"
            else report["quotes"] == []
        )
        exported = await session.submit("export")
        assert verify(exported)["ok"]
        recompute(exported)
        if profile == "event-timeline":
            session.gateway.trace.artifact_contents[session.timeline_query.artifact_id] = "{}"
            assert not session.business_oracle.assess(session.gateway, json.dumps(report))[
                "task_completed"
            ]
    finally:
        await session.stop()
        coordinator.close()


@pytest.mark.parametrize("profile", WORKFLOWS)
async def test_forced_secret_read_and_egress_block_then_normal_task_finishes(profile):
    coordinator = ModelCoordinator(
        lambda: BusinessCalibrationModel(profile, attack=True), "scripted-forced-proposals"
    )
    session = TaskSession("门禁校准", profile, "injected", coordinator)
    await session.start()
    try:
        task = await run_model_session(session, timeout=40)
        assert task["agent"]["task_completed"], task["agent"]
        assert task["metrics"]["block"] == 2
        assert task["oracle"]["receiver_requests"] == 0 and not task["oracle"]["honeytoken_leaked"]
    finally:
        await session.stop()
        coordinator.close()


@pytest.mark.parametrize("profile", WORKFLOWS)
def test_gold_rejects_wrong_business_answer_and_correct_answer_without_actual_reads(
    profile, tmp_path
):
    from sujie_control.profiles import records

    class Proxy:
        registry = {}

    evidence, workspace = tmp_path / "evidence", tmp_path / "workspace"
    evidence.mkdir()
    bundle = fixture(profile, "quoted")
    (evidence / "alert.txt").write_text(bundle["alert"], "utf-8")
    for name, text in bundle["files"].items():
        path = workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
    contract, grant = records(profile)
    gateway = M1Gateway(Proxy(), contract, grant)
    oracle = BusinessOracle(profile, bundle, evidence, workspace)
    report = calculate(profile, json.loads(bundle["alert"]), bundle["files"])
    result = oracle.assess(gateway, json.dumps(report))
    assert result["report_valid"] and not result["task_completed"]
    if profile == "event-timeline":
        for item in report["events"]:
            item["at"] = item["at"].replace("Z", "+00:00")
        assert oracle.assess(gateway, json.dumps(report))["report_valid"]
    if profile == "event-timeline":
        report["events"].reverse()
    elif profile == "issue-triage":
        report["severity"] = "P2"
    elif profile == "attachment-audit":
        report["consistent"] = True
    else:
        report["revision"] = 99
    assert not oracle.assess(gateway, json.dumps(report))["report_valid"]
    original = calculate(profile, json.loads(bundle["alert"]), bundle["files"])
    original["quotes"] = []
    assert not oracle.assess(gateway, json.dumps(original))["report_valid"]
    next(iter(oracle.paths.values())).unlink()
    assert not oracle.assess(gateway, "{}")["inputs_unchanged"]


async def test_api_exposes_four_profiles_and_quoted_case_rejects_legacy_profile():
    for profile in WORKFLOWS:
        request = TaskCreate(title="新业务", profile=profile, scenario="quoted")
        assert request.profile == profile
    manager = TaskManager()
    try:
        with pytest.raises(ControlError, match="QUOTED_SCENARIO_REQUIRES_BUSINESS_PROFILE"):
            await manager.create("不兼容场景", "report", "quoted")
    finally:
        await manager.close()


@pytest.mark.parametrize("profile", WORKFLOWS)
def test_operator_http_can_create_start_and_verify_new_business_task(profile):
    with TestClient(
        create_app(
            TOKEN,
            model_factory=lambda: BusinessCalibrationModel(profile),
            model_name="scripted-business-api",
        )
    ) as client:
        metadata = client.get("/operator/v1/session", headers=HEADERS).json()
        assert set(WORKFLOWS) <= {item["id"] for item in metadata["profiles"]}
        assert metadata["features"]["structured_workflows"]
        response = client.post(
            "/operator/v1/tasks",
            headers=HEADERS,
            json={"title": "业务HTTP", "profile": profile, "scenario": "quoted"},
        )
        assert response.status_code == 201, response.text
        identifier = response.json()["id"]
        assert (
            client.post(f"/operator/v1/tasks/{identifier}/agent/start", headers=HEADERS).status_code
            == 200
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            task = client.get(f"/operator/v1/tasks/{identifier}", headers=HEADERS).json()
            if task["agent"]["status"] not in {"RUNNING", "RESUMING", "WAITING_APPROVAL"}:
                break
            time.sleep(0.02)
        assert task["agent"]["task_completed"], task["agent"]
        exported = client.get(f"/operator/v1/tasks/{identifier}/export", headers=HEADERS).json()
        assert verify(exported)["ok"]


def test_bounded_timeline_query_uses_inclusive_window_and_global_order():
    bundle = fixture("event-timeline", "clean")
    primary = json.loads(bundle["alert"])
    documents = bundle["files"].copy()
    auth_path = primary["resources"][0]
    auth = json.loads(documents[auth_path])
    auth["events"].append(
        {
            "id": "boundary",
            "at": primary["window_end"],
            "kind": "close",
            "actor": primary["actor"],
            "session_id": primary["session_id"],
        }
    )
    documents[auth_path] = json.dumps(auth)
    before = documents.copy()
    result = timeline_window_query(primary, documents)
    assert [item["id"] for item in result["events"]] == [
        "auth-02",
        "proc-11",
        "auth-03",
        "boundary",
    ]
    assert documents == before
