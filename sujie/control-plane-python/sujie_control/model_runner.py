"""Operator model budget and metadata telemetry; no credential or dialog projections."""

from __future__ import annotations

import time
from collections.abc import Callable

from sujie_demo_agent.bailian_agent import ChatModel
from sujie_demo_agent.model_budget import ModelBudget

MODEL_SNAPSHOT = "qwen-plus-2025-12-01"
MAX_MODEL_CALLS = 6
MAX_TOOL_CALLS = 10


class ModelCoordinator:
    def __init__(
        self,
        factory: Callable[[], ChatModel] | None,
        model_name: str,
        max_runs: int = 10,
        *,
        budget: ModelBudget | None = None,
        approval_timeout: float = 300.0,
    ):
        self.factory, self.model_name, self.max_runs = factory, model_name, max_runs
        self.active_run: str | None = None
        self.started_runs = 0
        self.budget = budget or ModelBudget(max_requests=60, max_units=1_000_000)
        self.run_budgets: dict[str, ModelBudget] = {}
        if not 0 < approval_timeout <= 300:
            raise ValueError("INVALID_APPROVAL_TIMEOUT")
        self.approval_timeout = approval_timeout

    @property
    def active(self) -> bool:
        return self.active_run is not None

    def reserve(self, run_id: str) -> ChatModel:
        if self.factory is None:
            raise ValueError("MODEL_NOT_CONFIGURED")
        if self.active:
            raise ValueError("MODEL_BUSY")
        if self.started_runs >= self.max_runs:
            raise ValueError("MODEL_RUN_BUDGET_EXHAUSTED")
        available = self.budget.view()
        if not available["remaining_requests"]:
            raise ValueError("MODEL_BUDGET_REQUESTS_EXHAUSTED")
        if not available["remaining_units"]:
            raise ValueError("MODEL_BUDGET_UNITS_EXHAUSTED")
        try:
            model = self.factory()
        except Exception:
            raise ValueError("MODEL_FACTORY_FAILED") from None
        run_budget = self.budget.child(run_id)
        self.run_budgets[run_id] = run_budget
        self.active_run = run_id
        self.started_runs += 1
        return model

    def run_budget(self, run_id: str) -> ModelBudget:
        return self.run_budgets[run_id]

    def close(self) -> None:
        self.budget.ledger.close()

    def release(self, run_id: str) -> None:
        if self.active_run == run_id:
            self.active_run = None
        self.run_budgets.pop(run_id, None)

    def view(self) -> dict:
        return {
            "available": self.factory is not None,
            "model": self.model_name if self.factory else None,
            "active": self.active,
            "remaining_runs": max(0, self.max_runs - self.started_runs),
            "max_runs_per_service": self.max_runs,
            "max_model_calls_per_run": MAX_MODEL_CALLS,
            "max_tool_calls_per_run": MAX_TOOL_CALLS,
            "shared_budget": self.budget.view(),
        }


class ObservedModel:
    def __init__(self, model: ChatModel, state: dict):
        self.model, self.state = model, state

    @property
    def response_artifacts(self):
        return getattr(self.model, "response_artifacts", None)

    @property
    def response_event_id(self):
        return getattr(self.model, "response_event_id", None)

    async def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        self.state["model_requests"] += 1
        self.state["status"] = "RUNNING"
        self.state["phase"] = "MODEL_WAIT"
        started = time.perf_counter()
        try:
            response = await self.model.complete(messages, tools)
        finally:
            self.state["model_wait_ms"] += round((time.perf_counter() - started) * 1000, 2)
            usage = getattr(self.model, "usage", [])
            self.state["usage"] = {
                key: sum(row.get(key, 0) for row in usage if isinstance(row.get(key, 0), int))
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if any(type(row.get(key)) is int for row in usage)
            }
        self.state["model_responses"] += 1
        self.state["phase"] = "GATEWAY_EXECUTION"
        return response
