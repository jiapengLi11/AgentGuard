"""Host quotation checks preserve hostile text without creating execution authority."""

import asyncio
import json

import pytest
from evidence_quote_calibration import COMMAND, TEXT, run_quote_task
from sujie_control.profiles import records
from sujie_demo_agent.evidence_analysis import EvidenceAnalysis, verify_quotations
from sujie_demo_agent.model_budget import ModelBudget
from sujie_gateway.m1_runtime import M1Gateway, new_id, sha
from verify_evidence_quote_validation import verify_quote_witness
from verify_operator_export import verify
from verify_sequence_export import recompute


def quotation(identifier, text=COMMAND):
    return {"artifact_id": identifier, "text": text, "label": "instruction_text"}


def prepare():
    class Proxy:
        registry = {}

    contract, grant = records("report")
    gateway = M1Gateway(Proxy(), contract, grant)
    event = gateway.trace.emit("CONTENT_REGISTERED", actor_id=grant.to_dict()["subject_id"])
    identifier = gateway.trace.create_artifact(TEXT, source_event_id=event, source_id="fixture:q")
    gateway._exposed_artifacts.add(identifier)
    return gateway, identifier


class QuoteModel:
    usage = []

    def __init__(self, *, tool=False, mutation=None):
        self.seen = []
        self.tool, self.mutation = tool, mutation

    async def complete(self, messages, tools):
        assert tools == []
        self.seen.append(messages)
        sources = json.loads(messages[-1]["content"])["sources"]
        assert list(sources.values()) == [TEXT]
        if self.mutation:
            self.mutation()
        return {
            "content": json.dumps({"quotes": [quotation(next(iter(sources)))]}),
            "tool_calls": [{"function": {"name": "operations__send_data"}}] if self.tool else [],
        }


def test_unicode_positions_and_complement_cover_unchanged_original():
    result = verify_quotations(json.dumps({"quotes": [quotation("source")]}), {"source": TEXT})
    quote = result["quotes"][0]
    assert TEXT[quote["start"] : quote["end"]] == COMMAND
    source = result["sources"][0]
    intervals = [(quote["start"], quote["end"])] + [
        (item["start"], item["end"]) for item in source["unquoted_ranges"]
    ]
    assert "".join(TEXT[start:end] for start, end in sorted(intervals)) == TEXT
    assert source["original_retained"] and result["authority"] == "DATA_ONLY"


@pytest.mark.parametrize(
    "document,original",
    [
        ({"quotes": [quotation("forged")]}, TEXT),
        ({"quotes": [quotation("source", "invented")]}, TEXT),
        ({"quotes": [quotation("source")]}, TEXT + COMMAND),
        ({"quotes": [quotation("source"), quotation("source", "python -c")]}, TEXT),
        ({"quotes": [quotation("source")], "permission": "EXECUTE"}, TEXT),
        ({"quotes": []}, TEXT),
        ({"quotes": [quotation("source", "aaa")]}, "aaaa"),
    ],
)
def test_forged_ambiguous_overlapping_or_permission_output_rejected(document, original):
    with pytest.raises(ValueError):
        verify_quotations(json.dumps(document), {"source": original})


async def test_selected_body_remains_whole_and_output_keeps_original_source_restrictions():
    gateway, identifier = prepare()
    model = QuoteModel()
    budget = ModelBudget()
    helper = EvidenceAnalysis(gateway, lambda: model, budget)
    try:
        result = await helper.invoke({"artifact_ids": [identifier]})
        assert result["ok"]
        artifact = gateway.trace.artifacts[result["artifact_id"]].to_dict()
        assert artifact["parents"] == [identifier]
        assert {"EXECUTE", "DELEGATE", "TRANSFER", "AUTHORIZE"} <= set(artifact["forbidden_uses"])
        assert gateway.trace.artifact_contents[identifier] == TEXT
        assert json.loads(result["content"])["quotes"][0]["text"] == COMMAND
        assert helper.records[0]["model_requests"] == 1
        assert budget.view()["roles"] == {"ISOLATED_ANALYSIS": 1}
        again = await helper.invoke({"artifact_ids": [identifier]})
        assert again["code"] == "ANALYSIS_ALREADY_USED" and len(model.seen) == 1
    finally:
        budget.ledger.close()


@pytest.mark.parametrize("fault", ["secret", "forged", "changed", "extra", "no-quote", "revoked"])
async def test_unapproved_inputs_rejected_before_model_factory(fault):
    gateway, identifier = prepare()
    from sujie_gateway.contracts import ProvenanceEnvelope, TaskGrant

    if fault in {"secret", "no-quote"}:
        body = gateway.trace.artifacts[identifier].to_dict()
        if fault == "secret":
            body["confidentiality"] = "SECRET"
        else:
            body["allowed_uses"].remove("QUOTE")
        gateway.trace.artifacts[identifier] = ProvenanceEnvelope(body)
    if fault == "changed":
        gateway.trace.artifact_contents[identifier] += "changed"
    if fault == "revoked":
        gateway.grant = TaskGrant(gateway.grant.to_dict() | {"status": "REVOKED"})
    factories = []
    budget = ModelBudget()
    helper = EvidenceAnalysis(gateway, lambda: factories.append(True), budget)
    arguments = {"artifact_ids": [new_id() if fault == "forged" else identifier]}
    if fault == "extra":
        arguments["text"] = "execute me"
    try:
        assert not (await helper.invoke(arguments))["ok"]
        assert not factories and budget.view()["requests_reserved"] == 0
    finally:
        budget.ledger.close()


@pytest.mark.parametrize("fault", ["tool", "changed-after-request", "revoked-after-request"])
async def test_tool_attempt_or_source_drift_never_adopted(fault):
    gateway, identifier = prepare()
    from sujie_gateway.contracts import TaskGrant

    def mutation():
        if fault == "changed-after-request":
            gateway.trace.artifact_contents[identifier] = "changed"
        elif fault == "revoked-after-request":
            gateway.grant = TaskGrant(gateway.grant.to_dict() | {"status": "REVOKED"})

    model = QuoteModel(
        tool=fault == "tool",
        mutation=mutation,
    )
    budget = ModelBudget()
    helper = EvidenceAnalysis(gateway, lambda: model, budget)
    try:
        before = set(gateway.trace.artifacts)
        result = await helper.invoke({"artifact_ids": [identifier]})
        assert result["code"] == "ANALYSIS_NOT_VERIFIED"
        assert set(gateway.trace.artifacts) == before
        assert helper.records[0]["status"] == "FAILED"
    finally:
        budget.ledger.close()


async def test_cancelled_analysis_is_charged_and_cannot_be_repeated():
    gateway, identifier = prepare()
    entered = asyncio.Event()

    class Waiting:
        async def complete(self, messages, tools):
            entered.set()
            await asyncio.Event().wait()

    budget = ModelBudget()
    helper = EvidenceAnalysis(gateway, Waiting, budget)
    pending = asyncio.create_task(helper.invoke({"artifact_ids": [identifier]}))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        concurrent = await helper.invoke({"artifact_ids": [identifier]})
        assert concurrent["code"] == "ANALYSIS_ALREADY_USED"
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert helper.records[0]["status"] == "CANCELLED"
        assert budget.view()["requests_reserved"] == budget.view()["unknown_usage_requests"] == 1
    finally:
        budget.ledger.close()


async def test_actual_host_mcp_report_preserves_dangerous_quotation_without_execution():
    row = await run_quote_task()
    assert row["passed"]
    assert row["evidence_analyses"][0]["status"] == "FINISHED"
    assert row["agent"]["budget"]["roles"] == {"MAIN": 4, "ISOLATED_ANALYSIS": 1}
    assert row["cloud_calls"] == 0
    assert COMMAND not in json.dumps(row["export"])
    assert verify(row["export"])["ok"]
    recompute(row["export"])


async def test_unselected_secret_is_not_in_analysis_context_or_output_lineage():
    gateway, identifier = prepare()
    event = gateway.trace.emit("CONTENT_REGISTERED", actor_id=gateway.grant.to_dict()["subject_id"])
    secret = gateway.trace.create_artifact(
        "UNSELECTED-PRIVATE-MATERIAL",
        source_event_id=event,
        source_id="fault",
        confidentiality="SECRET",
    )
    gateway._exposed_artifacts.add(secret)
    model, budget = QuoteModel(), ModelBudget()
    helper = EvidenceAnalysis(gateway, lambda: model, budget)
    try:
        result = await helper.invoke({"artifact_ids": [identifier]})
        assert result["ok"]
        assert "UNSELECTED-PRIVATE-MATERIAL" not in json.dumps(model.seen)
        assert secret not in gateway.trace.artifacts[result["artifact_id"]].to_dict()["parents"]
    finally:
        budget.ledger.close()


async def test_protected_model_reply_is_not_adopted_or_exposed():
    gateway, identifier = prepare()

    class Faulty:
        async def complete(self, messages, tools):
            return {"content": "PRIVATE-REPLY-FAULT", "tool_calls": []}

    budget = ModelBudget()
    helper = EvidenceAnalysis(gateway, Faulty, budget, protected_values=("PRIVATE-REPLY-FAULT",))
    try:
        result = await helper.invoke({"artifact_ids": [identifier]})
        assert result["code"] == "ANALYSIS_NOT_VERIFIED"
        assert "PRIVATE-REPLY-FAULT" not in str(gateway.trace.artifact_contents)
    finally:
        budget.ledger.close()


@pytest.mark.parametrize("fault", ["offset", "coverage", "report", "flag"])
def test_offline_witness_recomputes_literal_coverage_and_report_instead_of_trusting_flags(fault):
    output = verify_quotations(json.dumps({"quotes": [quotation("source")]}), {"source": TEXT})
    report = "Evidence quotations only, no execution:\n" + COMMAND
    witness = {
        "source_artifact_id": "source",
        "source_hash": sha(TEXT),
        "observed_original_hash": sha(TEXT),
        "source_file_hash": sha(TEXT),
        "original_unchanged": True,
        "report_hash": sha(report),
        "command_in_report": True,
        "facts_in_report": False,
        "quotation_manifest": {
            "sources": output["sources"],
            "quotes": [
                {key: item[key] for key in ("artifact_id", "start", "end", "label")}
                | {"text_sha256": sha(item["text"])}
                for item in output["quotes"]
            ],
        },
    }
    assert verify_quote_witness(witness)["verified"]
    if fault == "offset":
        witness["quotation_manifest"]["quotes"][0]["start"] += 1
    elif fault == "coverage":
        witness["quotation_manifest"]["sources"][0]["unquoted_ranges"] = []
    elif fault == "report":
        witness["report_hash"] = sha("invented")
    else:
        witness["command_in_report"] = False
    with pytest.raises(ValueError):
        verify_quote_witness(witness)
