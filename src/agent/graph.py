"""HelpDesk Lite graph skeleton with mock nodes.

extract_fields -> (ask_clarification) -> retrieve_policy -> check_graph -> decide_action
    -> (human_approval -> execute_action) -> respond

Pauses: langgraph 0.2.45 (our pinned version) has no interrupt()/Command(resume=...), so the graph
uses static breakpoints. Callers resume through start(), reply() and decide() and never touch the
breakpoint mechanics, so upgrading langgraph later only changes this file.
"""

from typing import Any, Optional

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agent import nodes
from src.agent.models import ActionStatus, AgentState


def route_after_extract(state: AgentState) -> str:
    return "ask_clarification" if state.needs_clarification else "retrieve_policy"


def route_after_decide(state: AgentState) -> str:
    return "human_approval" if state.action_proposal.requires_approval else "respond"


def route_after_approval(state: AgentState) -> str:
    return "execute_action" if state.action_proposal.status == ActionStatus.APPROVED else "respond"


def build_graph(
    checkpointer: Optional[BaseCheckpointSaver] = None,
    *,
    use_postgres: bool = False,
) -> CompiledStateGraph:
    """Build and compile the HelpDesk Lite agent workflow graph.

    Args:
        checkpointer: Optional custom BaseCheckpointSaver instance.
        use_postgres: When True and checkpointer is None, initializes PostgresSaver for
                      durable state persistence across process restarts. Falls back to
                      MemorySaver if the database connection fails.
    """
    if checkpointer is None:
        if use_postgres:
            try:
                from src.db.checkpointer import PostgresSaver

                checkpointer = PostgresSaver()
            except Exception:
                checkpointer = MemorySaver()
        else:
            checkpointer = MemorySaver()

    builder = StateGraph(AgentState)
    for node in (
        nodes.extract_fields,
        nodes.ask_clarification,
        nodes.retrieve_policy,
        nodes.check_graph,
        nodes.decide_action,
        nodes.human_approval,
        nodes.execute_action,
        nodes.respond,  # "final_response" in the contract; that name is taken by the state field
    ):
        builder.add_node(node.__name__, node)

    builder.add_edge(START, "extract_fields")
    builder.add_conditional_edges("extract_fields", route_after_extract, ["ask_clarification", "retrieve_policy"])
    builder.add_edge("ask_clarification", "extract_fields")
    builder.add_edge("retrieve_policy", "check_graph")
    builder.add_edge("check_graph", "decide_action")
    builder.add_conditional_edges("decide_action", route_after_decide, ["human_approval", "respond"])
    builder.add_conditional_edges("human_approval", route_after_approval, ["execute_action", "respond"])
    builder.add_edge("execute_action", "respond")
    builder.add_edge("respond", END)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_after=["ask_clarification"],  # question posted, wait for the user's reply
        interrupt_before=["human_approval"],  # proposal pending, wait for the operator
    )


def get_production_graph() -> CompiledStateGraph:
    """Instantiate production LangGraph compiled with persistent PostgresSaver."""
    return build_graph(use_postgres=True)


def config_for(
    thread_id: str,
    user_email: Optional[str] = None,
    *,
    action_id: Optional[str] = None,
    tags: Optional[list[str]] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build LangGraph config attaching configurable, metadata, and tags for LangSmith tracing."""
    run_metadata: dict[str, Any] = {"thread_id": thread_id}
    if user_email:
        run_metadata["user_email"] = user_email
    if action_id:
        run_metadata["action_id"] = action_id
    if metadata:
        run_metadata.update(metadata)

    run_tags = list(tags) if tags else []

    return {
        "configurable": {"thread_id": thread_id, "user_email": user_email},
        "metadata": run_metadata,
        "tags": run_tags,
    }


def pending(graph: CompiledStateGraph, config: dict) -> Optional[str]:
    """What the paused graph waits for: "clarification", "approval", or None when it finished."""
    waiting = graph.get_state(config).next
    if "human_approval" in waiting:
        return "approval"
    if "extract_fields" in waiting:
        return "clarification"
    return None


def start(graph: CompiledStateGraph, config: dict, request: str) -> dict:
    thread_id = config.get("configurable", {}).get("thread_id", "")
    meta = config.setdefault("metadata", {})
    if thread_id and "thread_id" not in meta:
        meta["thread_id"] = thread_id
    if user_email := config.get("configurable", {}).get("user_email"):
        meta.setdefault("user_email", user_email)
    config.setdefault("tags", [])
    return graph.invoke({"thread_id": thread_id, "messages": [{"role": "user", "content": request}]}, config)


def reply(graph: CompiledStateGraph, config: dict, answer: str) -> dict:
    """Resume after ask_clarification with the user's answer."""
    messages = graph.get_state(config).values["messages"]
    graph.update_state(config, {"messages": [*messages, {"role": "user", "content": answer}]})
    thread_id = config.get("configurable", {}).get("thread_id", "")
    meta = config.setdefault("metadata", {})
    if thread_id and "thread_id" not in meta:
        meta["thread_id"] = thread_id
    return graph.invoke(None, config)


def decide(graph: CompiledStateGraph, config: dict, approved: bool) -> dict:
    """Resume before human_approval with the operator's decision.

    Guarded: only processes decisions while the graph is waiting for approval.
    Prevents lifecycle regressions (e.g. executed -> approved) on replayed decisions.
    Attaches action_id and thread_id to LangSmith trace metadata for resumed runs.
    """
    if pending(graph, config) != "approval":
        return graph.get_state(config).values
    proposal = graph.get_state(config).values["action_proposal"]
    status = ActionStatus.APPROVED if approved else ActionStatus.REJECTED
    graph.update_state(config, {"action_proposal": proposal.model_copy(update={"status": status})})

    meta = config.setdefault("metadata", {})
    thread_id = config.get("configurable", {}).get("thread_id", "")
    if thread_id:
        meta["thread_id"] = thread_id
    if proposal and proposal.action_id:
        meta["action_id"] = proposal.action_id

    return graph.invoke(None, config)
