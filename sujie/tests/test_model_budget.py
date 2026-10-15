"""Request admission, cancellation and restart must share the same model budget."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sujie_control.api import create_app
from sujie_control.runtime import TaskManager
from sujie_demo_agent.bailian_agent import ModelProtocolError
from sujie_demo_agent.model_budget import BudgetError, BudgetLedger, ModelBudget
from sujie_demo_agent.protected_model import ProtectedModel
from test_operator_agent import ReportModel, finished, start
from test_operator_api import HEADERS, TOKEN, create_task


def test_all_roles_and_sibling_tasks_share_parent_request_limit():
    root = ModelBudget(max_requests=2, max_units=100)
    first, second = root.child("first"), root.child("second")
    first.settle(first.reserve("MAIN", 20), status="RETURNED", reported_tokens=7)
    second.settle(second.reserve("SUBAGENT", 20), status="RETURNED", reported_tokens=9)
    with pytest.raises(BudgetError, match="MODEL_BUDGET_REQUESTS_EXHAUSTED"):
        first.reserve("RECOVERY", 1)
    assert root.view()["charged_units"] == 16
    assert root.view()["roles"] == {"MAIN": 1, "SUBAGENT": 1}
    root.ledger.close()


def test_pending_failed_cancelled_usage_and_replay_are_not_refunded():
    root = ModelBudget(max_requests=10, max_units=100)
    pending = root.reserve("CLASSIFY", 30)
    cancelled = root.reserve("RECOVERY", 30)
    root.settle(cancelled, status="CANCELLED", reported_tokens=None)
    failed = root.reserve("SUBAGENT", 30)
    root.settle(failed, status="FAILED", reported_tokens=None)
    assert root.view()["charged_units"] == 90
    assert root.view()["unknown_usage_requests"] == 3
    assert root.view()["pending_requests"] == 1
    with pytest.raises(BudgetError, match="MODEL_BUDGET_UNITS_EXHAUSTED"):
        root.reserve("MAIN", 11)
    with pytest.raises(BudgetError, match="MODEL_BUDGET_SETTLEMENT_INVALID"):
        root.settle(cancelled, status="RETURNED", reported_tokens=0)
    root.settle(pending, status="RETURNED", reported_tokens=5)
    assert root.view()["charged_units"] == 65
    root.ledger.close()


def test_provider_usage_over_estimate_is_charged_and_stops_next_request():
    root = ModelBudget(max_requests=10, max_units=20)
    root.settle(root.reserve("MAIN", 10), status="RETURNED", reported_tokens=25)
    assert root.view()["estimate_exceeded"]
    assert root.view()["billing_bound"] == "NOT_GUARANTEED"
    with pytest.raises(BudgetError, match="MODEL_BUDGET_UNITS_EXHAUSTED"):
        root.reserve("MAIN", 1)
    root.ledger.close()


def test_durable_pending_survives_restart_and_limits_cannot_silently_change(tmp_path):
    path = tmp_path / "budget.sqlite3"
    first = ModelBudget(ledger=BudgetLedger(path), max_requests=1, max_units=100)
    first.reserve("MAIN", 70)
    first.ledger.close()  # Simulate losing the completion before it is persisted.
    ledger = BudgetLedger(path)
    restarted = ModelBudget(ledger=ledger, max_requests=1, max_units=100)
    assert restarted.view()["pending_requests"] == 1
    assert restarted.view()["charged_units"] == 70
    with pytest.raises(BudgetError, match="MODEL_BUDGET_REQUESTS_EXHAUSTED"):
        restarted.reserve("RECOVERY", 1)
    with pytest.raises(BudgetError, match="MODEL_BUDGET_CONFIG_MISMATCH"):
        ModelBudget(ledger=ledger, max_requests=2, max_units=100)
    ledger.close()


def test_two_independent_connections_cannot_over_admit_last_request(tmp_path):
    path = tmp_path / "budget.sqlite3"
    ledgers = [BudgetLedger(path), BudgetLedger(path)]
    budgets = [ModelBudget(ledger=ledger, max_requests=1, max_units=100) for ledger in ledgers]

    def attempt(budget):
        try:
            budget.reserve("MAIN", 10)
            return "ADMITTED"
        except BudgetError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, budgets))
    assert sorted(results) == ["ADMITTED", "MODEL_BUDGET_REQUESTS_EXHAUSTED"]
    assert all(budget.view()["requests_reserved"] == 1 for budget in budgets)
    for ledger in ledgers:
        ledger.close()


@pytest.mark.asyncio
async def test_guarded_role_wrappers_refuse_before_backend_and_record_returned_usage():
    class Backend:
        def __init__(self):
            self.calls = 0
            self.usage = []

        async def complete(self, messages, tools):
            self.calls += 1
            self.usage.append({"total_tokens": 9})
            return {"content": "public answer"}

    manager = TaskManager()
    task = await manager.create("角色共享预算", "report", "clean")
    budget = ModelBudget(max_requests=2, max_units=10000)
    backend = Backend()
    protected = ProtectedModel(backend, manager.get(task["id"]).gateway, budget=budget)
    try:
        await protected.complete([{"role": "user", "content": "public"}], [])
        await protected.for_purpose("CLASSIFY").complete(
            [{"role": "user", "content": "public"}], []
        )
        with pytest.raises(ModelProtocolError, match="MODEL_BUDGET_REQUESTS_EXHAUSTED"):
            await protected.for_purpose("SUBAGENT").complete(
                [{"role": "user", "content": "public"}], []
            )
        assert backend.calls == 2
        assert budget.view()["reported_tokens"] == 18
        assert budget.view()["unknown_usage_requests"] == 0
    finally:
        await manager.close()
        budget.ledger.close()


@pytest.mark.asyncio
async def test_cancellation_after_backend_entry_preserves_reservation():
    entered = asyncio.Event()

    class Backend:
        async def complete(self, messages, tools):
            entered.set()
            await asyncio.Event().wait()

    manager = TaskManager()
    task = await manager.create("取消预算", "report", "clean")
    budget = ModelBudget(max_requests=1, max_units=10000)
    protected = ProtectedModel(Backend(), manager.get(task["id"]).gateway, budget=budget)
    try:
        running = asyncio.create_task(
            protected.complete([{"role": "user", "content": "public"}], [])
        )
        await entered.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
        assert budget.view()["requests_reserved"] == 1
        assert budget.view()["unknown_usage_requests"] == 1
        assert budget.view()["pending_requests"] == 0
        assert budget.view()["charged_units"] > 0
    finally:
        await manager.close()
        budget.ledger.close()


def test_operator_restart_keeps_provider_budget_and_rejects_new_run_before_factory(tmp_path):
    path = tmp_path / "operator-budget.sqlite3"
    created = []

    def factory():
        backend = ReportModel()
        created.append(backend)
        return backend

    kwargs = dict(model_factory=factory, model_budget_path=path, max_provider_requests=3)
    with TestClient(create_app(TOKEN, **kwargs)) as client:
        identifier = create_task(client)
        assert start(client, identifier).status_code == 200
        result = finished(client, identifier)
        assert result["agent"]["task_completed"]
        assert result["agent"]["budget"]["reported_tokens"] == 360
        shared = client.get("/operator/v1/session", headers=HEADERS).json()["model"][
            "shared_budget"
        ]
        assert shared["requests_reserved"] == 3
        assert shared["durable"]
    with TestClient(create_app(TOKEN, **kwargs)) as client:
        identifier = create_task(client)
        assert start(client, identifier).json()["detail"] == "MODEL_BUDGET_REQUESTS_EXHAUSTED"
        assert len(created) == 1
        assert not client.get("/operator/v1/session", headers=HEADERS).json()["model"]["active"]
