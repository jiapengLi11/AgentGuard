"""Common fixture fingerprints, observed model recipes and one finite approval rule."""

import asyncio
import hashlib
import time

from sujie_gateway.m1_runtime import sha
from sujie_gateway.model_context import canonical, digest


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def logical_fixture(session):
    root = session.workspace.parent
    data = {
        "profile": session.profile,
        "scenario": session.scenario,
        "workspace_files": {
            str(path.relative_to(session.workspace)).replace("\\", "/"): file_hash(path)
            for path in sorted(session.workspace.rglob("*"))
            if path.is_file()
        },
        "evidence_files": {
            path.name: file_hash(path)
            for path in sorted((root / "evidence").iterdir())
            if path.is_file()
        },
        "contract": {
            key: session.gateway.contract.to_dict()[key]
            for key in (
                "trusted_goal",
                "workspace_roots",
                "allowed_purposes",
                "allowed_effects",
                "forbidden_effects",
                "budgets",
            )
        },
        "grant": {
            key: session.gateway.grant.to_dict()[key]
            for key in ("effects", "resource_scopes", "budgets")
        },
    }
    instance = {}
    if session.gateway.network_policy:
        data["web_article_sha256"] = hashlib.sha256(
            session.web_fixture.article.encode()
        ).hexdigest()
        config = session.gateway.network_policy.to_dict()
        instance["network_aliases_hash"] = sha(config["aliases"])
        data["network"] = {key: value for key, value in config.items() if key != "aliases"}
    if session.gateway.execution_policy:
        data["execution"] = session.gateway.execution_policy.to_dict()
    if session.git_fixture:
        config = session.git_fixture.policy.to_dict()
        instance["git_config_and_layout_hash"] = sha(config)
        data["git"] = {
            key: config[key]
            for key in (
                "remote",
                "ref",
                "commit",
                "expected_old",
                "timeout_seconds",
                "git_sha256",
                "head_file_sha256",
            )
        }
    if session.memory_workflow:
        data["memory"] = session.memory_workflow.snapshot()
    return {
        "logical": data,
        "logical_hash": sha(data),
        "instance_bindings": instance,
        "nonce_policy": "paired task ID and fixed Git commit epoch; process/artifact IDs, physical aliases/layouts, creation/expiry times are instance bindings, not business input differences",
    }


def model_recipe(model):
    credentials = getattr(model, "_credentials", None)
    return {
        "backend_class": type(model).__name__,
        "model": getattr(model, "model", "scripted-test-model"),
        "max_tokens": getattr(model, "max_tokens", 512),
        "timeout": getattr(model, "timeout", None),
        "temperature": 0 if credentials is not None else None,
        "endpoint_hash": sha(credentials.base_url) if credentials is not None else None,
        "scope": "observed provider attributes and archived backend recipe; content hash is not a complete HTTP-wire attestation",
    }


class RecordedModel:
    def __init__(self, backend, records):
        self.backend, self.records = backend, records
        self.recipe = model_recipe(backend)
        self.node = {"recipe": self.recipe, "recipe_hash": sha(self.recipe), "requests": []}
        records.append(self.node)

    @property
    def model(self):
        return getattr(self.backend, "model", "scripted-test-model")

    @property
    def max_tokens(self):
        return getattr(self.backend, "max_tokens", 512)

    @property
    def usage(self):
        return getattr(self.backend, "usage", [])

    async def complete(self, messages, tools):
        if model_recipe(self.backend) != self.recipe:
            raise ValueError("PAIRED_MODEL_CONFIGURATION_DRIFT")
        self.node["requests"].append(
            {
                "content_hash": digest(canonical({"messages": messages, "tools": tools})),
                "system_hash": sha(messages[0]),
                "tools_hash": sha(tools),
            }
        )
        return await self.backend.complete(messages, tools)


async def approved_call(gateway, tool, arguments):
    result = await gateway.call(tool, arguments)
    if result.get("decision") != "ASK":
        return result
    principal = gateway.contract.to_dict()["principal_id"]
    approval = await gateway.approve(result["decision_id"], principal)
    if not approval.get("ok"):
        return approval
    return await gateway.commit(result["decision_id"])


async def run_model_session(session, timeout=240):
    await session.submit("agent_start")
    deadline = time.monotonic() + timeout
    reviewed = set()
    while time.monotonic() < deadline:
        task = await session.submit("view")
        if task["agent"]["status"] == "WAITING_APPROVAL":
            pending = next(
                item
                for item in task["approvals"]
                if item["decision_id"] == task["agent"]["waiting_decision_id"]
            )
            if pending["decision_id"] not in reviewed:
                # Predeclared sealed-range test principal approves every pinned ASK.
                # No attack labels, model variant, or utility answer enter this rule.
                reviewed.add(pending["decision_id"])
                result = await session.submit(
                    "approval", (pending["decision_id"], "approve", pending["review_hash"])
                )
                if result.get("ok"):
                    await session.submit(
                        "approval", (pending["decision_id"], "commit", pending["review_hash"])
                    )
        if task["agent"]["status"] not in {"RUNNING", "WAITING_APPROVAL", "RESUMING"}:
            return task
        await asyncio.sleep(0.05)
    await session.submit("agent_cancel")
    return await session.submit("view")


def verify_pair(rows, *, require_model=False):
    if not rows or len({row["variant"] for row in rows}) != len(rows):
        raise ValueError("UNPAIRED_VARIANTS")
    if len({row["fixture"]["logical_hash"] for row in rows}) != 1:
        raise ValueError("PAIRED_LOGICAL_FIXTURE_MISMATCH")
    if require_model:
        first = [row["models"][0] for row in rows if row["models"] and row["models"][0]["requests"]]
        if (
            len(first) != len(rows)
            or len({item["recipe_hash"] for item in first}) != 1
            or len({item["requests"][0]["content_hash"] for item in first}) != 1
        ):
            raise ValueError("PAIRED_MODEL_OR_INITIAL_REQUEST_MISMATCH")
    return {
        "ok": True,
        "variants": [row["variant"] for row in rows],
        "logical_hash": rows[0]["fixture"]["logical_hash"],
        "initial_model_request_checked": require_model,
        "scope": "same logical initial fixture and initial model request; subsequent generated IDs, outputs and trajectories may differ",
    }
