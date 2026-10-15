"""A later secret cannot taint an earlier response; unbound rewrites stay guarded."""

import pytest
from sujie_control.runtime import TaskManager
from sujie_demo_agent.bailian_agent import ModelProtocolError
from sujie_demo_agent.protected_model import ProtectedModel


@pytest.mark.asyncio
async def test_response_lineage_binds_actual_request_not_later_exposure():
    class Backend:
        async def complete(self, messages, tools):
            return {"content": "public answer", "tool_calls": []}

    manager = TaskManager()
    task = await manager.create("时序来源", "report", "clean")
    session = manager.get(task["id"])
    protected = ProtectedModel(Backend(), session.gateway)
    try:
        messages = [{"role": "user", "content": "public request"}]
        response = await protected.complete(messages, [])
        event = session.gateway.trace.emit(
            "CONTENT_REGISTERED", actor_id=session.id, payload={"kind": "HOST_FAULT"}
        )
        private = session.gateway.trace.create_artifact(
            "secret material unique 9834",
            source_event_id=event,
            source_id="fault",
            confidentiality="SECRET",
        )
        session.gateway._exposed_artifacts.add(private)
        messages.append({"role": "assistant", "content": response["content"]})
        await protected.complete(messages, [])
        latest = next(
            event
            for event in reversed(session.gateway.trace.events)
            if event["event_type"] == "MODEL_REQUEST_CHECKED"
        )
        fields = session.gateway.trace.payloads[latest["event_id"]]["fields"]
        assert all(private not in field["inherited_artifacts"] for field in fields)
        derived = session.gateway.record_model_output(
            "public generated output",
            input_artifacts=protected.response_artifacts,
            response_event_id=protected.response_event_id,
        )
        envelope = session.gateway.trace.artifacts[derived].to_dict()
        assert envelope["confidentiality"] == "INTERNAL"
        assert private not in envelope["parents"]
        messages[0]["content"] = "a different preceding conversation"
        with pytest.raises(ModelProtocolError, match="MODEL_EGRESS_CLASSIFICATION"):
            await protected.complete(messages, [])
    finally:
        protected.budget.ledger.close()
        await manager.close()


@pytest.mark.asyncio
async def test_unobserved_rewrite_still_inherits_current_sensitive_context():
    class Backend:
        async def complete(self, messages, tools):
            raise AssertionError("MUST_NOT_FORWARD")

    manager = TaskManager()
    task = await manager.create("未知改写", "report", "clean")
    session = manager.get(task["id"])
    protected = ProtectedModel(Backend(), session.gateway)
    try:
        event = session.gateway.trace.emit(
            "CONTENT_REGISTERED", actor_id=session.id, payload={"kind": "HOST_FAULT"}
        )
        private = session.gateway.trace.create_artifact(
            "private data 8452", source_event_id=event, source_id="fault", confidentiality="SECRET"
        )
        session.gateway._exposed_artifacts.add(private)
        with pytest.raises(ModelProtocolError, match="MODEL_EGRESS_CLASSIFICATION"):
            await protected.complete([{"role": "assistant", "content": "unregistered rewrite"}], [])
    finally:
        protected.budget.ledger.close()
        await manager.close()
