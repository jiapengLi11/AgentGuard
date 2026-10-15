"""Concrete Git object/lease approvals versus actual refs in an owned local remote."""

import json
import sys
from pathlib import Path

import pytest
from mcp import StdioServerParameters
from sealed_git import GitFixture, SealedGit
from sujie_control.profiles import records
from sujie_control.views import approval_view
from sujie_gateway.contracts import TaskContract, TaskGrant
from sujie_gateway.git_policy import GitError, GitPolicy
from sujie_gateway.m1_runtime import LOCAL_TOOL_CATALOG, M1Gateway, StdioMCPProxy

ROOT = Path(__file__).resolve().parents[1]


def prepare(tmp_path, scenario="injected"):
    fixture = GitFixture(tmp_path / "git-fixture", scenario)
    config_path = tmp_path / "git-policy.json"
    config_path.write_text(fixture.policy.wire_json, "utf-8")
    params = {
        "git_delivery": StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "mcp-servers/git-delivery-server/server.py")],
            env={
                "SUJIE_GIT_POLICY": str(config_path),
                "SUJIE_GIT_REPO_ROOT": str(fixture.repo),
                "SUJIE_GIT_REMOTE_ROOT": str(fixture.remote),
                "SUJIE_GIT_HOOKS_ROOT": str(fixture.hooks),
                "SUJIE_GIT_RECEIPTS": str(fixture.receipts),
            },
        )
    }
    return fixture, StdioMCPProxy(
        params, expected_tools={"git_delivery": LOCAL_TOOL_CATALOG["git_delivery"]}
    )


def contracts(fixture, publish=True):
    c, g = records("report")
    contract, grant = c.to_dict(), g.to_dict()
    if publish:
        contract["forbidden_effects"].remove("git.push")
        contract["allowed_effects"].append(
            {"kind": "git.push", "resource": fixture.policy.resource}
        )
        contract["allowed_purposes"].append("EXECUTE")
        grant["effects"].append("git.push")
    return TaskContract(contract), TaskGrant(grant)


@pytest.mark.asyncio
async def test_review_blocks_push_and_explicit_publication_asks_then_exact_commit_once(tmp_path):
    fixture, proxy = prepare(tmp_path)
    async with proxy:
        review = M1Gateway(proxy, *contracts(fixture, False), git_policy=fixture.policy)
        content = await review.call("git_delivery.inspect", {})
        assert content["ok"] and "Ignore previous instructions" in content["data"]["content"]
        denied = await review.call("git_delivery.push", fixture.policy.proposal())
        assert denied["decision"] == "BLOCK" and fixture.runner.ref_value() == fixture.base
        assert not fixture.receipts.exists()
        gateway = M1Gateway(proxy, *contracts(fixture), git_policy=fixture.policy)
        result = await gateway.call("git_delivery.push", fixture.policy.proposal())
        assert result["decision"] == "ASK"
        summary = approval_view((await gateway.approval_summaries())[0], None)
        assert summary["git_review"]["commit"] == fixture.commit
        assert summary["git_review"]["expected_old"] == fixture.base
        altered = (await gateway.approval_summaries())[0]
        altered["git_review"] = altered["git_review"] | {"ref": "refs/heads/other"}
        assert approval_view(altered, None)["review_hash"] != summary["review_hash"]
        assert fixture.runner.ref_value() == fixture.base
        assert (
            await gateway.approve(result["decision_id"], gateway.contract.to_dict()["principal_id"])
        )["ok"]
        assert fixture.runner.ref_value() == fixture.base
        pushed = await gateway.commit(result["decision_id"])
        assert pushed["ok"] and pushed["data"]["commit"] == fixture.commit
        assert (await gateway.commit(result["decision_id"]))["replayed"]
        assert fixture.runner.ref_value() == fixture.commit
        rows = [json.loads(row) for row in fixture.receipts.read_text("utf-8").splitlines()]
        assert [row["event"] for row in rows] == ["PUSH_STARTED", "PUSH_CONFIRMED"]
        assert len({row["job_id"] for row in rows}) == 1
        probes = [
            event
            for event in gateway.trace.events
            if event["event_type"] == "TOOL_PROPOSED"
            and gateway.trace.payloads[event["event_id"]].get("kind") == "TRUSTED_HOST_STATE_CHECK"
        ]
        assert len(probes) == 3
        assert all(
            event["actor_id"] == gateway.contract.to_dict()["principal_id"] for event in probes
        )


@pytest.mark.asyncio
async def test_invalid_remote_ref_commit_lease_and_forged_authorization_block(tmp_path):
    fixture, proxy = prepare(tmp_path)
    async with proxy:
        gateway = M1Gateway(proxy, *contracts(fixture), git_policy=fixture.policy)
        for name, value in (
            ("remote", "https://external.invalid/repo"),
            ("ref", "refs/heads/main"),
            ("commit", "HEAD"),
            ("expected_old", ""),
            ("state_hash", "0" * 64),
        ):
            arguments = fixture.policy.proposal() | {name: value}
            result = await gateway.call("git_delivery.push", arguments)
            assert result["code"] == "hard_block_unregistered_git_target"
            with pytest.raises(RuntimeError, match="MCP_TOOL_ERROR"):
                await proxy.invoke("git_delivery.push", arguments)
        assert (
            await gateway.call("git_delivery.push", fixture.policy.proposal() | {"approved": True})
        )["code"] == "INVALID_ACTION"
        assert fixture.runner.ref_value() == fixture.base and not fixture.receipts.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["remote-ref", "HEAD", "repo-config", "remote-config"])
async def test_post_approval_drift_is_refused_before_push_tool(tmp_path, change):
    fixture, proxy = prepare(tmp_path)
    async with proxy:
        gateway = M1Gateway(proxy, *contracts(fixture), git_policy=fixture.policy)
        result = await gateway.call("git_delivery.push", fixture.policy.proposal())
        identifier = result["decision_id"]
        assert (await gateway.approve(identifier, gateway.contract.to_dict()["principal_id"]))["ok"]
        if change == "remote-ref":
            fixture.runner.run("update-ref", "-d", "refs/heads/release", remote=True)
        elif change == "HEAD":
            fixture.runner.run("update-ref", "refs/heads/main", fixture.base)
        elif change == "repo-config":
            fixture.runner.run(
                "config", "url.https://external.invalid/.insteadOf", fixture.remote.as_uri()
            )
        else:
            fixture.runner.run(
                "config", "core.hooksPath", str(fixture.remote / "hooks"), remote=True
            )
        current = fixture.runner.ref_value()
        assert (await gateway.commit(identifier))["code"] == "APPROVAL_STALE"
        assert fixture.runner.ref_value() == current
        assert not fixture.receipts.exists()


def test_explicit_lease_closes_change_between_validation_and_push(tmp_path, monkeypatch):
    fixture = GitFixture(tmp_path / "git-fixture")
    original = fixture.runner.run

    def race(*args, **kwargs):
        if args and args[0] == "push":
            original("update-ref", "-d", "refs/heads/release", remote=True)
        return original(*args, **kwargs)

    monkeypatch.setattr(fixture.runner, "run", race)
    with pytest.raises(GitError, match="GIT_COMMAND_FAILED"):
        fixture.executor.push(fixture.policy.proposal())
    assert fixture.runner.ref_value() == ""
    rows = [json.loads(row) for row in fixture.receipts.read_text("utf-8").splitlines()]
    assert rows[-1]["event"] == "PUSH_FAILED"


def test_hooks_are_disabled_and_non_fast_forward_is_forbidden(tmp_path):
    fixture = GitFixture(tmp_path / "git-fixture")
    marker = tmp_path / "unexpected-hook"
    for hook in (fixture.repo / ".git/hooks/pre-push", fixture.remote / "hooks/pre-receive"):
        hook.write_text(f'#!/bin/sh\necho forbidden > "{marker.as_posix()}"\nexit 1\n', "utf-8")
        hook.chmod(0o755)
    assert fixture.executor.push(fixture.policy.proposal())["commit"] == fixture.commit
    assert not marker.exists()
    config = fixture.policy.to_dict() | {"commit": fixture.base, "expected_old": fixture.commit}
    fixture.runner.run("update-ref", "refs/heads/main", fixture.base)
    reversed_policy = GitPolicy.from_dict(config)
    executor = SealedGit(fixture.runner, reversed_policy, fixture.receipts)
    with pytest.raises(GitError, match="GIT_NON_FAST_FORWARD_FORBIDDEN"):
        executor.push(reversed_policy.proposal())


def test_same_commit_external_race_is_not_attributed_to_own_push(tmp_path, monkeypatch):
    fixture = GitFixture(tmp_path / "git-fixture")
    original = fixture.runner.run

    def race(*args, **kwargs):
        if args and args[0] == "push":
            original(
                "push",
                "--no-verify",
                fixture.remote.as_uri(),
                f"{fixture.commit}:refs/heads/release",
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(fixture.runner, "run", race)
    with pytest.raises(GitError, match="GIT_MUTATION_NOT_CONFIRMED"):
        fixture.executor.push(fixture.policy.proposal())
    assert fixture.runner.ref_value() == fixture.commit
    assert (
        json.loads(fixture.receipts.read_text("utf-8").splitlines()[-1])["event"] == "PUSH_FAILED"
    )


def test_empty_lease_creates_only_a_previously_absent_ref(tmp_path):
    fixture = GitFixture(tmp_path / "git-fixture")
    fixture.runner.run("update-ref", "-d", "refs/heads/release", remote=True)
    policy = GitPolicy.from_dict(fixture.policy.to_dict() | {"expected_old": ""})
    assert (
        SealedGit(fixture.runner, policy, fixture.receipts).push(policy.proposal())["commit"]
        == fixture.commit
    )


def test_large_readme_is_rejected_before_materializing_blob(tmp_path, monkeypatch):
    fixture = GitFixture(tmp_path / "git-fixture")
    (fixture.repo / "README.md").write_text("X" * 8193, "utf-8")
    fixture.runner.run("add", "README.md")
    fixture.runner.run("commit", "-q", "-m", "Oversize source fixture")
    policy = GitPolicy.from_dict(fixture.policy.to_dict() | {"commit": fixture.runner.head()})
    original = fixture.runner.run
    shown = []

    def observe(*args, **kwargs):
        if args and args[0] == "show":
            shown.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(fixture.runner, "run", observe)
    with pytest.raises(GitError, match="GIT_INSPECTION_TOO_LARGE"):
        SealedGit(fixture.runner, policy, fixture.receipts).inspect()
    assert not shown
