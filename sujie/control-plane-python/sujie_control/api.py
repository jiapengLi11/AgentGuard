"""Authenticated operator endpoints; never mounted on the Agent-facing application."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sujie_demo_agent.bailian_agent import ChatModel
from sujie_demo_agent.model_budget import BudgetLedger, ModelBudget
from sujie_gateway.m1_runtime import M1Policy

from .model_runner import MODEL_SNAPSHOT, ModelCoordinator
from .profiles import PROFILES
from .runtime import ControlError, TaskManager

bearer = HTTPBearer(auto_error=False)


class BoundedRequestBody:
    """Bound streamed bodies before JSON parsing, including chunked requests."""

    def __init__(self, app, max_bytes: int = 32768):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        chunks, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.max_bytes:
                response = JSONResponse({"detail": "REQUEST_TOO_LARGE"}, status_code=413)
                return await response(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)
    profile: Literal[
        "report",
        "ioc-transfer",
        "web-report",
        "artifact-verify",
        "git-review",
        "git-publish",
        "delegated-report",
        "memory-review",
        "memory-update",
        "event-timeline",
        "issue-triage",
        "attachment-audit",
        "knowledge-reconcile",
    ] = "report"
    scenario: Literal["clean", "injected", "quoted"] = "injected"
    user_message: str | None = Field(default=None, min_length=1, max_length=4096)


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal[
        "read_evidence",
        "probe_private",
        "probe_egress",
        "write_report",
        "prepare_ioc",
        "request_ioc_transfer",
    ]


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_hash: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


def create_app(
    operator_token: str,
    *,
    dist_dir: Path | None = None,
    model_factory: Callable[[], ChatModel] | None = None,
    model_name: str = MODEL_SNAPSHOT,
    max_model_runs: int = 10,
    model_budget_path: Path | None = None,
    max_provider_requests: int = 60,
    max_reservation_units: int = 1_000_000,
    approval_timeout: float = 300.0,
) -> FastAPI:
    if (
        not isinstance(operator_token, str)
        or not 32 <= len(operator_token) <= 128
        or not operator_token.isascii()
    ):
        raise ValueError("INVALID_OPERATOR_TOKEN")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        budget = ModelBudget(
            ledger=BudgetLedger(model_budget_path),
            max_requests=max_provider_requests,
            max_units=max_reservation_units,
        )
        app.state.manager = TaskManager(
            ModelCoordinator(
                model_factory,
                model_name,
                max_model_runs,
                budget=budget,
                approval_timeout=approval_timeout,
            )
        )
        try:
            yield
        finally:
            await app.state.manager.close()

    app = FastAPI(
        title="Sujie Operator Control",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    app.add_middleware(BoundedRequestBody)

    async def authenticated(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        token = credentials.credentials if credentials else ""
        if len(token) > 128 or not secrets.compare_digest(
            token.encode("utf-8"), operator_token.encode("ascii")
        ):
            raise HTTPException(
                401, "OPERATOR_AUTH_REQUIRED", headers={"WWW-Authenticate": "Bearer"}
            )
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            raise HTTPException(403, "OPERATOR_ORIGIN_MISMATCH")

    @app.middleware("http")
    async def response_headers(request: Request, call_next):
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 32768:
            return JSONResponse({"detail": "REQUEST_TOO_LARGE"}, status_code=413)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(ControlError)
    async def control_error(request: Request, error: ControlError):
        return JSONResponse({"detail": str(error)}, status_code=error.status)

    @app.get("/healthz")
    async def health():
        return {"status": "ok", "surface": "operator"}

    router = APIRouter(prefix="/operator/v1", dependencies=[Depends(authenticated)])

    @router.get("/session")
    async def session(request: Request):
        return {
            "actor": "本机操作者",
            "mode": "sealed-local-demo",
            "ephemeral": True,
            "profiles": [{"id": key, **value} for key, value in PROFILES.items()],
            "model": request.app.state.manager.models.view(),
            "features": {
                "context_audit": True,
                "scoped_user_input": True,
                "model_approval": True,
                "web_report": True,
                "artifact_verify": True,
                "git_delivery": True,
                "delegated_report": True,
                "memory_cycle": True,
                "structured_workflows": True,
            },
            "schema_bundle_version": "0.2",
        }

    @router.get("/policy")
    async def policy():
        current = M1Policy()
        source = Path(__file__).resolve().parents[2] / "gateway-python/policies/m1.yaml"
        return {
            "snapshot_hash": current.snapshot_hash,
            "dsl": source.read_text("utf-8"),
            "editable": False,
        }

    @router.get("/tasks")
    async def tasks(request: Request):
        return {"tasks": await request.app.state.manager.summaries()}

    @router.post("/tasks", status_code=201)
    async def create_task(payload: TaskCreate, request: Request):
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="INVALID_TASK_TITLE")
        return await request.app.state.manager.create(
            title, payload.profile, payload.scenario, user_message=payload.user_message
        )

    @router.get("/tasks/{task_id}")
    async def task(task_id: str, request: Request):
        return await request.app.state.manager.get(task_id).submit("view")

    @router.delete("/tasks/{task_id}")
    async def close_task(task_id: str, request: Request):
        await request.app.state.manager.remove(task_id)
        return {"ok": True}

    @router.get("/tasks/{task_id}/export")
    async def export_task(task_id: str, request: Request):
        return await request.app.state.manager.get(task_id).submit("export")

    @router.get("/tasks/{task_id}/contexts")
    async def contexts(task_id: str, request: Request):
        return await request.app.state.manager.get(task_id).submit("contexts")

    @router.post("/tasks/{task_id}/actions")
    async def action(task_id: str, payload: ActionRequest, request: Request):
        return await request.app.state.manager.get(task_id).submit("action", payload.operation)

    @router.post("/tasks/{task_id}/agent/{operation}")
    async def agent(operation: Literal["start", "cancel"], task_id: str, request: Request):
        return await request.app.state.manager.get(task_id).submit(f"agent_{operation}")

    @router.get("/tasks/{task_id}/impact/{artifact_id}")
    async def impact(task_id: str, artifact_id: str, request: Request):
        return await request.app.state.manager.get(task_id).submit("impact", artifact_id)

    @router.post("/tasks/{task_id}/approvals/{decision_id}/{operation}")
    async def approval(
        task_id: str,
        decision_id: str,
        operation: Literal["approve", "reject", "commit"],
        payload: ApprovalRequest,
        request: Request,
    ):
        return await request.app.state.manager.get(task_id).submit(
            "approval", (decision_id, operation, payload.review_hash)
        )

    app.include_router(router)
    if dist_dir is not None:
        dist = dist_dir.resolve()
        if not (dist / "index.html").is_file():
            raise ValueError("CONSOLE_BUILD_MISSING")
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        async def index():
            return FileResponse(dist / "index.html")

    return app
