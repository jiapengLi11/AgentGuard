"""Normal paths share inputs, while ablations remain narrow through nested roles."""

import pytest
from evaluation_models import calibration_backend
from paired_runtime import RecordedModel, logical_fixture, run_model_session, verify_pair
from runtime_variants import VARIANTS, TrialTaskSession, Variant
from sujie_control.model_runner import ModelCoordinator
from sujie_gateway.m1_runtime import new_id
from verify_operator_export import verify
from verify_sequence_export import recompute


@pytest.mark.parametrize(
    "profile",
    [
        "report",
        "ioc-transfer",
        "web-report",
        "artifact-verify",
        "git-review",
        "git-publish",
        "delegated-report",
        "memory-review",
        "memory-update",
    ],
)
async def test_full_and_strong_static_use_same_initial_inputs_and_finish_legal_goals(profile):
    rows = []
    identifier = new_id()
    for variant in ("full", "strong-static"):
        models = []
        coordinator = ModelCoordinator(
            lambda: RecordedModel(calibration_backend(profile), models), "scripted-common-runtime"
        )
        session = TrialTaskSession(
            "合法对照", profile, "clean", coordinator, variant=variant, paired_scope_id=identifier
        )
        await session.start()
        try:
            fixture = logical_fixture(session)
            detail = await run_model_session(session, timeout=60)
            assert detail["agent"]["task_completed"], detail["agent"]
            exported = await session.submit("export")
            assert verify(exported)["ok"]
            recompute(exported)
            if profile == "delegated-report":
                bindings = [
                    event["details"].get("variant")
                    for event in detail["events"]
                    if event["details"].get("kind") == "EVALUATION_RUNTIME_VARIANT"
                ]
                assert bindings == [variant] * 3
            rows.append({"variant": variant, "fixture": fixture, "models": models})
        finally:
            await session.stop()
            coordinator.close()
    assert verify_pair(rows, require_model=True)["ok"]


async def test_no_recovery_removes_host_reminder_but_keeps_normal_model_loop():
    rows = []
    identifier = new_id()
    for variant in VARIANTS:
        models = []
        coordinator = ModelCoordinator(
            lambda: RecordedModel(calibration_backend("report", premature=True), models),
            "scripted-premature",
        )
        session = TrialTaskSession(
            "有界提醒", "report", "clean", coordinator, variant=variant, paired_scope_id=identifier
        )
        await session.start()
        try:
            fixture = logical_fixture(session)
            detail = await run_model_session(session, timeout=30)
            assert detail["agent"]["task_completed"] == (variant != "no-recovery")
            assert detail["agent"]["completion_reminders"] == (0 if variant == "no-recovery" else 1)
            rows.append({"variant": variant, "fixture": fixture, "models": models})
        finally:
            await session.stop()
            coordinator.close()
    assert verify_pair(rows, require_model=True)["ok"]


def test_ablation_recipes_only_remove_the_declared_mechanism():
    full = Variant("full").recipe()
    for name, field in (
        ("no-source", "source_use_decisions"),
        ("no-recovery", "host_recovery_notes_and_completion_reminder"),
    ):
        other = Variant(name).recipe()
        assert {key for key in full if full[key] != other[key]} == {"name", field}


@pytest.mark.parametrize("profile", ["delegated-report", "memory-update"])
@pytest.mark.parametrize("variant", ["no-source", "no-recovery"])
async def test_ablations_propagate_through_actual_nested_models(profile, variant):
    models = []
    coordinator = ModelCoordinator(
        lambda: RecordedModel(calibration_backend(profile), models), "scripted-nested-ablation"
    )
    session = TrialTaskSession(
        "嵌套消融", profile, "clean", coordinator, variant=variant, paired_scope_id=new_id()
    )
    await session.start()
    try:
        detail = await run_model_session(session, timeout=60)
        assert detail["agent"]["task_completed"], detail["agent"]
        bindings = [
            event["details"].get("variant")
            for event in detail["events"]
            if event["details"].get("kind") == "EVALUATION_RUNTIME_VARIANT"
        ]
        assert bindings == [variant] * 3
        if profile == "memory-update":
            assert all(
                node["contract"]["policy_snapshot_hash"] == Variant(variant).policy_hash
                for node in detail["memory_sessions"]
            )
    finally:
        await session.stop()
        coordinator.close()
