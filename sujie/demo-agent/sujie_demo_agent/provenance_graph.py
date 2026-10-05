"""M2 LangGraph workflow: pause for ASK, then continue the authorized local report."""

from collections.abc import Callable
from typing import Protocol, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .graph import GatewayClient


class SummaryModel(Protocol):
    def summarize(self, evidence: str) -> str: ...


class DeterministicSummaryModel:
    """Stable synthetic model; deliberately omits the secret but cannot remove its lineage."""

    def summarize(self, evidence: str) -> str:
        return "告警已分析；原始材料保留在本地，摘要建议人工复核。"


class ProvenanceState(TypedDict, total=False):
    resource: str
    content: str
    summary: str
    decisions: list[dict]
    approval_decision_id: str
    completed: bool


def build_provenance_agent(
    gateway: GatewayClient, model: SummaryModel, prepare_content: Callable[[dict], str]
):
    async def read(state):
        result = await gateway.call("operations.read_file", {"resource": state["resource"]})
        if not result["ok"]:
            return {"decisions": [result], "completed": False}
        # Trusted Host adapter decodes/registers the view before exposing it to the model.
        return {"content": prepare_content(result), "decisions": [result]}

    def summarize(state):
        return {"summary": model.summarize(state["content"])}

    async def propose(state):
        result = await gateway.call(
            "operations.send_data", {"destination": "receiver", "content": state["summary"]}
        )
        updates = {"decisions": state["decisions"] + [result]}
        if result["decision"] == "ASK":
            updates["approval_decision_id"] = result["decision_id"]
        return updates

    def wait_for_approval(state):
        # Text/Command resume has no authorization power. Only the host commits at the gateway.
        result = interrupt({"decision_id": state["approval_decision_id"]})
        return {"decisions": state["decisions"] + [result]}

    async def report(state):
        result = await gateway.call(
            "operations.write_file",
            {
                "resource": "case-001/output/report.txt",
                "content": "安全研判报告\n" + state["summary"],
            },
        )
        return {"decisions": state["decisions"] + [result], "completed": result["ok"]}

    graph = StateGraph(ProvenanceState)
    for name, node in (
        ("read", read),
        ("summarize", summarize),
        ("propose", propose),
        ("wait", wait_for_approval),
        ("report", report),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "read")
    graph.add_conditional_edges(
        "read",
        lambda state: "summarize" if state["decisions"][-1]["ok"] else END,
        {"summarize": "summarize", END: END},
    )
    graph.add_edge("summarize", "propose")
    graph.add_conditional_edges(
        "propose",
        lambda state: "wait" if state["decisions"][-1]["decision"] == "ASK" else "report",
        {"wait": "wait", "report": "report"},
    )
    graph.add_edge("wait", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=InMemorySaver(), name="sujie-m2-provenance")
