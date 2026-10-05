"""M1 boundary regressions with real MCP processes and synthetic side-effect oracles."""

import asyncio
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from mcp import StdioServerParameters
from receiver import Receiver
from sujie_demo_agent.graph import DeterministicDecisionModel, build_agent
from sujie_gateway import m1_runtime
from sujie_gateway.contracts import TaskContract, TaskGrant, TraceEvent
from sujie_gateway.m1_runtime import M1Gateway, StdioMCPProxy, new_id

ROOT = Path(__file__).resolve().parents[1]
CANARY = "SYNTHETIC-M1-BOUNDARY-CANARY"
DESTINATION = "https://receiver.invalid/upload"


@pytest.fixture
def runtime_factory(tmp_path, fixture_document):
    @asynccontextmanager
    async def open_runtime():
        evidence, workspace = tmp_path / "evidence", tmp_path / "workspace"
        evidence.mkdir()
        (evidence / "clean.txt").write_text("合成告警，请生成本地报告。", "utf-8")
        case = workspace / "case-001"
        case.mkdir(parents=True)
        (case / "secret.txt").write_text(CANARY, "utf-8")
        c, g = fixture_document("task-contract"), fixture_document("task-grant")
        c["expires_at"] = g["expires_at"] = "2099-01-01T00:00:00Z"
        c["budgets"] = {"tool_calls": 8, "network_calls": 0, "subagents": 0}
        g["budgets"] = {"tool_calls": 8}
        with Receiver() as receiver:
            params = {
                "evidence": StdioServerParameters(
                    command=sys.executable,
                    args=[str(ROOT / "mcp-servers/evidence-server/server.py")],
                    env={"SUJIE_EVIDENCE_ROOT": str(evidence)},
                ),
                "operations": StdioServerParameters(
                    command=sys.executable,
                    args=[str(ROOT / "mcp-servers/operations-server/server.py")],
                    env={
                        "SUJIE_WORKSPACE_ROOT": str(workspace),
                        "SUJIE_RECEIVER_URL": receiver.url,
                    },
                ),
            }
            async with StdioMCPProxy(params) as proxy:
                yield proxy, c, g, workspace, receiver

    return open_runtime


def gateway_for(runtime):
    proxy, c, g, _, _ = runtime
    return M1Gateway(proxy, TaskContract(c), TaskGrant(g))


def permit_transfer(runtime):
    _, c, g, _, _ = runtime
    c["allowed_effects"].append({"kind": "data.transfer", "resource": DESTINATION})
    c["forbidden_effects"].remove("external.data_transfer")
    c["budgets"]["network_calls"] = 3
    g["effects"].append("data.transfer")
    g["resource_scopes"].append(DESTINATION)
    g["budgets"]["network_calls"] = 3


@pytest.mark.parametrize(
    "invalid", ["expired_contract", "expired_grant", "zero_contract", "zero_grant", "foreign_grant"]
)
async def test_M1_BOUNDARY_001_invalid_authority_never_writes(runtime_factory, invalid):
    async with runtime_factory() as boundary_runtime:
        _, c, g, workspace, receiver = boundary_runtime
        if invalid.startswith("expired"):
            (c if invalid == "expired_contract" else g)["expires_at"] = "2020-01-01T00:00:00Z"
        elif invalid.startswith("zero"):
            (c if invalid == "zero_contract" else g)["budgets"]["tool_calls"] = 0
        else:
            g["contract_id"] = new_id()
        result = await gateway_for(boundary_runtime).call(
            "operations.write_file",
            {"resource": "case-001/output/report.txt", "content": "synthetic"},
        )
        assert result["decision"] == "BLOCK"
        assert not result["ok"]
        assert not (workspace / "case-001/output/report.txt").exists()
        assert (workspace / "case-001/secret.txt").read_text("utf-8") == CANARY
        assert receiver.bodies == []


async def test_M1_BOUNDARY_002_concurrent_allow_cannot_exceed_budget(runtime_factory):
    async with runtime_factory() as boundary_runtime:
        _, c, g, workspace, _ = boundary_runtime
        c["budgets"]["tool_calls"] = g["budgets"]["tool_calls"] = 1
        gateway = gateway_for(boundary_runtime)
        results = await asyncio.gather(
            *(
                gateway.call(
                    "operations.write_file",
                    {"resource": f"case-001/output/report-{i}.txt", "content": "synthetic"},
                )
                for i in range(5)
            )
        )
        assert sum(result["ok"] for result in results) == 1
        assert sum(result["decision"] == "BLOCK" for result in results) == 4
        assert len(list((workspace / "case-001/output").glob("*.txt"))) == 1
        for event in gateway.trace.events:
            TraceEvent(event)


async def test_M1_BOUNDARY_003_block_does_not_spend_execution_budget(runtime_factory):
    async with runtime_factory() as boundary_runtime:
        _, c, g, workspace, _ = boundary_runtime
        c["budgets"]["tool_calls"] = g["budgets"]["tool_calls"] = 1
        gateway = gateway_for(boundary_runtime)
        blocked = await gateway.call("operations.read_file", {"resource": "case-001/secret.txt"})
        assert blocked["decision"] == "BLOCK"
        written = await gateway.call(
            "operations.write_file",
            {"resource": "case-001/output/report.txt", "content": "synthetic"},
        )
        assert written["ok"]
        assert (workspace / "case-001/output/report.txt").read_text("utf-8") == "synthetic"


async def test_M1_BOUNDARY_004_failed_dispatch_still_spends_budget(runtime_factory):
    async with runtime_factory() as boundary_runtime:
        _, c, g, workspace, _ = boundary_runtime
        c["budgets"]["tool_calls"] = g["budgets"]["tool_calls"] = 1
        gateway = gateway_for(boundary_runtime)
        failed = await gateway.call("operations.read_file", {"resource": "case-001/missing.txt"})
        assert not failed["ok"]
        blocked = await gateway.call(
            "operations.write_file",
            {"resource": "case-001/output/report.txt", "content": "synthetic"},
        )
        assert blocked["decision"] == "BLOCK"
        assert not (workspace / "case-001/output/report.txt").exists()


@pytest.mark.parametrize("forbidden", ["data.transfer", "external.data_transfer"])
async def test_M1_BOUNDARY_005_external_hard_block_cannot_be_approved(runtime_factory, forbidden):
    async with runtime_factory() as boundary_runtime:
        permit_transfer(boundary_runtime)
        _, c, _, _, receiver = boundary_runtime
        c["forbidden_effects"].append(forbidden)
        gateway = gateway_for(boundary_runtime)
        result = await gateway.call(
            "operations.send_data", {"destination": "receiver", "content": "SYNTHETIC-NONSECRET"}
        )
        assert result["decision"] == "BLOCK"
        assert result["code"] == "CONTRACT_FORBIDS_EFFECT"
        assert not (await gateway.approve(result["decision_id"], c["principal_id"]))["ok"]
        assert not (await gateway.commit(result["decision_id"]))["ok"]
        assert receiver.bodies == []


@pytest.mark.parametrize("limited", ["contract", "grant", "missing_grant_dimension"])
async def test_M1_BOUNDARY_006_zero_network_budget_never_posts(runtime_factory, limited):
    async with runtime_factory() as boundary_runtime:
        permit_transfer(boundary_runtime)
        _, c, g, _, receiver = boundary_runtime
        if limited == "missing_grant_dimension":
            del g["budgets"]["network_calls"]
        else:
            (c if limited == "contract" else g)["budgets"]["network_calls"] = 0
        result = await gateway_for(boundary_runtime).call(
            "operations.send_data", {"destination": "receiver", "content": "SYNTHETIC-NONSECRET"}
        )
        assert result["decision"] == "BLOCK"
        assert receiver.bodies == []


async def test_M1_BOUNDARY_007_grant_must_include_network_target(runtime_factory):
    async with runtime_factory() as boundary_runtime:
        permit_transfer(boundary_runtime)
        _, _, g, _, receiver = boundary_runtime
        g["resource_scopes"].remove(DESTINATION)
        result = await gateway_for(boundary_runtime).call(
            "operations.send_data", {"destination": "receiver", "content": "SYNTHETIC-NONSECRET"}
        )
        assert result["decision"] == "BLOCK"
        assert result["code"] == "RESOURCE_OUT_OF_SCOPE"
        assert receiver.bodies == []


@pytest.mark.parametrize("dimension", ["tool_calls", "network_calls"])
async def test_M1_BOUNDARY_008_pending_asks_share_one_execution_budget(runtime_factory, dimension):
    async with runtime_factory() as boundary_runtime:
        permit_transfer(boundary_runtime)
        _, c, g, _, receiver = boundary_runtime
        c["budgets"][dimension] = g["budgets"][dimension] = 1
        gateway = gateway_for(boundary_runtime)
        proposals = [
            await gateway.call(
                "operations.send_data", {"destination": "receiver", "content": f"SYNTHETIC-{i}"}
            )
            for i in range(2)
        ]
        assert all(p["decision"] == "ASK" for p in proposals)
        assert receiver.bodies == []
        for proposal in proposals:
            assert (await gateway.approve(proposal["decision_id"], c["principal_id"]))["ok"]
        results = await asyncio.gather(*(gateway.commit(p["decision_id"]) for p in proposals))
        assert sum(result["ok"] for result in results) == 1
        assert len(receiver.bodies) == 1
        winner = next(p for p, result in zip(proposals, results, strict=True) if result["ok"])
        assert (await gateway.commit(winner["decision_id"]))["replayed"]
        assert len(receiver.bodies) == 1


@pytest.mark.parametrize("change", ["expires", "revoked"])
async def test_M1_BOUNDARY_009_recheck_after_tool_discovery(runtime_factory, monkeypatch, change):
    async with runtime_factory() as boundary_runtime:
        proxy, c, g, workspace, _ = boundary_runtime
        clock = datetime(2030, 1, 1, tzinfo=timezone.utc)
        c["expires_at"] = g["expires_at"] = "2030-01-01T00:00:01Z"
        monkeypatch.setattr(m1_runtime, "utc_now", lambda: clock)
        gateway = gateway_for(boundary_runtime)
        client = proxy._clients["operations"]
        original = client.list_tools

        async def changed_discovery(*args, **kwargs):
            nonlocal clock
            result = await original(*args, **kwargs)
            if change == "expires":
                clock += timedelta(seconds=2)
            else:
                revoked = gateway.grant.to_dict()
                revoked["status"] = "REVOKED"
                gateway.grant = TaskGrant(revoked)
            return result

        monkeypatch.setattr(client, "list_tools", changed_discovery)
        result = await gateway.call(
            "operations.write_file",
            {"resource": "case-001/output/report.txt", "content": "synthetic"},
        )
        assert result["decision"] == "BLOCK"
        assert not result["ok"]
        assert not (workspace / "case-001/output/report.txt").exists()


async def test_M1_BOUNDARY_010_materialized_arguments_cannot_change_during_discovery(
    runtime_factory, monkeypatch
):
    async with runtime_factory() as boundary_runtime:
        proxy, _, _, workspace, _ = boundary_runtime
        gateway = gateway_for(boundary_runtime)
        arguments = {"resource": "case-001/output/report.txt", "content": "synthetic"}
        client = proxy._clients["operations"]
        original = client.list_tools

        async def changed_discovery(*args, **kwargs):
            result = await original(*args, **kwargs)
            arguments["resource"] = "case-001/secret.txt"
            return result

        monkeypatch.setattr(client, "list_tools", changed_discovery)
        assert (await gateway.call("operations.write_file", arguments))["ok"]
        assert (workspace / "case-001/output/report.txt").read_text("utf-8") == "synthetic"
        assert (workspace / "case-001/secret.txt").read_text("utf-8") == CANARY


@pytest.mark.parametrize("link_kind", ["read", "write", "directory", "dangling", "outside"])
async def test_M1_BOUNDARY_011_symlink_paths_have_no_secret_side_effect(
    runtime_factory, link_kind, tmp_path
):
    async with runtime_factory() as boundary_runtime:
        _, _, _, workspace, receiver = boundary_runtime
        case = workspace / "case-001"
        (case / "output").mkdir()
        target = case / "secret.txt"
        if link_kind == "outside":
            target = tmp_path / "outside.txt"
            target.write_text(CANARY, "utf-8")
        elif link_kind == "dangling":
            target = case / "must-not-create.txt"
        link = case / ("alias.txt" if link_kind in {"read", "outside"} else "output/alias.txt")
        if link_kind == "directory":
            target = case
        try:
            link.symlink_to(target, target_is_directory=link_kind == "directory")
        except OSError as error:
            if sys.platform != "win32":
                raise
            pytest.skip(f"Windows symlink privilege unavailable: {error.winerror}")
        resource = str(link.relative_to(workspace)).replace("\\", "/")
        if link_kind == "directory":
            resource += "/secret.txt"
        read = link_kind in {"read", "outside"}
        arguments = {"resource": resource}
        if not read:
            arguments["content"] = "SYNTHETIC-OVERWRITE"
        result = await gateway_for(boundary_runtime).call(
            "operations.read_file" if read else "operations.write_file", arguments
        )
        assert not result["ok"]
        assert CANARY not in str(result)
        assert (case / "secret.txt").read_text("utf-8") == CANARY
        assert not (case / "must-not-create.txt").exists()
        if link_kind == "outside":
            assert target.read_text("utf-8") == CANARY
        assert receiver.bodies == []


async def test_M1_BOUNDARY_012_regular_paths_remain_usable(runtime_factory):
    async with runtime_factory() as boundary_runtime:
        gateway = gateway_for(boundary_runtime)
        resource = "case-001/output/nested/report.txt"
        assert (
            await gateway.call("operations.write_file", {"resource": resource, "content": "正常"})
        )["ok"]
        result = await gateway.call("operations.read_file", {"resource": resource})
        assert result["ok"]
        assert result["data"]["content"] == "正常"


async def test_M1_BOUNDARY_013_missing_evidence_ends_workflow(runtime_factory):
    async with runtime_factory() as boundary_runtime:
        gateway = gateway_for(boundary_runtime)
        result = await build_agent(gateway, DeterministicDecisionModel()).ainvoke(
            {"alert_id": "missing"}
        )
        assert not result["completed"]
        assert len(result["decisions"]) == 1
        assert "report" not in result
        assert not (boundary_runtime[3] / "case-001/output/report.txt").exists()


async def test_M1_BOUNDARY_014_contract_change_before_approval_is_not_rebound(runtime_factory):
    async with runtime_factory() as boundary_runtime:
        permit_transfer(boundary_runtime)
        _, c, _, _, receiver = boundary_runtime
        gateway = gateway_for(boundary_runtime)
        asked = await gateway.call(
            "operations.send_data", {"destination": "receiver", "content": "SYNTHETIC-NONSECRET"}
        )
        changed = gateway.contract.to_dict()
        changed["version"] += 1
        gateway.contract = TaskContract(changed)
        assert await gateway.approve(asked["decision_id"], c["principal_id"]) == {
            "ok": False,
            "code": "APPROVAL_STALE",
        }
        assert not (await gateway.commit(asked["decision_id"]))["ok"]
        assert receiver.bodies == []


@pytest.mark.parametrize("change", ["expiry", "contract", "grant"])
async def test_M1_BOUNDARY_015_approval_rechecked_after_discovery(
    runtime_factory, monkeypatch, change
):
    async with runtime_factory() as boundary_runtime:
        permit_transfer(boundary_runtime)
        proxy, c, _, _, receiver = boundary_runtime
        clock = datetime(2030, 1, 1, tzinfo=timezone.utc)
        monkeypatch.setattr(m1_runtime, "utc_now", lambda: clock)
        gateway = gateway_for(boundary_runtime)
        asked = await gateway.call(
            "operations.send_data", {"destination": "receiver", "content": "SYNTHETIC-NONSECRET"}
        )
        assert (await gateway.approve(asked["decision_id"], c["principal_id"]))["ok"]
        client = proxy._clients["operations"]
        original = client.list_tools

        async def changed_discovery(*args, **kwargs):
            nonlocal clock
            result = await original(*args, **kwargs)
            if change == "expiry":
                clock += timedelta(seconds=301)
            elif change == "contract":
                changed = gateway.contract.to_dict()
                changed["version"] += 1
                gateway.contract = TaskContract(changed)
            else:
                changed = gateway.grant.to_dict()
                changed["budgets"]["tool_calls"] += 1
                gateway.grant = TaskGrant(changed)
            return result

        monkeypatch.setattr(client, "list_tools", changed_discovery)
        result = await gateway.commit(asked["decision_id"])
        assert not result["ok"]
        assert result["code"] == "APPROVAL_STALE"
        assert receiver.bodies == []
        assert (await gateway.commit(asked["decision_id"]))["replayed"]
        assert receiver.bodies == []
