"""Graph skeleton: routing, interrupts, approval and idempotency with mock nodes."""

import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver

from src.agent import nodes
from src.agent.graph import (
    build_graph,
    config_for,
    decide,
    get_production_graph,
    pending,
    reply,
    start,
)
from src.agent.models import ActionProposal, ActionStatus, ActionType, AgentState
from src.db.checkpointer import PostgresSaver
from src.db.connection import get_pooled_connection, is_postgres_available

MARIA = "maria.papadopoulou@nimbus.com"  # Finance, Athens
EMP02 = "employee02@nimbus.com"

requires_postgres = pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL database not available at localhost:5432",
)


@pytest.fixture
def graph():
    return build_graph()


def new_config(email=MARIA):
    return config_for(str(uuid.uuid4()), email)


def test_policy_question_is_answered_with_latest_citation(graph):
    config = new_config(EMP02)
    result = start(graph, config, "What is the Wi-Fi policy for visitors?")
    assert pending(graph, config) is None
    assert result["action_proposal"].action_type == ActionType.ANSWER_POLICY
    assert result["policy_result"].doc_id == "POL-016"
    assert "POL-016 (effective 2026-01-05)" in result["final_response"]


def test_polite_request_is_not_a_policy_question(graph):
    config = new_config()
    start(graph, config, "Can you reset my ERP System password?")
    assert pending(graph, config) == "approval"
    assert graph.get_state(config).values["action_proposal"].action_type == ActionType.RESET_CREDENTIALS


def test_outage_links_instead_of_resetting(graph):
    config = new_config()
    result = start(graph, config, "I can't connect to the VPN, please reset my password")
    proposal = result["action_proposal"]
    assert proposal.action_type == ActionType.LINK_OUTAGE
    assert not proposal.requires_approval
    assert "Identity Provider (SSO)" in result["graph_result"].active_outages
    # Latest version of the reset policy, not v1.
    assert result["policy_result"].effective_date == "2026-09-01"


def test_missing_fields_ask_and_resume_with_reply(graph):
    config = new_config()
    result = start(graph, config, "Please reset my password")
    assert pending(graph, config) == "clarification"
    assert result["messages"][-1]["role"] == "assistant"
    assert "application" in result["clarification_question"]

    result = reply(graph, config, "It is the ERP System")
    assert result["extracted_fields"].application == "ERP System"
    assert pending(graph, config) == "approval"
    assert result["action_proposal"].action_type == ActionType.RESET_CREDENTIALS
    assert result["action_proposal"].status == ActionStatus.PENDING


def test_graph_pauses_at_clarification_interrupt(graph):
    """Execution pauses at ask_clarification interrupt node when mandatory fields are missing."""
    config = new_config()
    result = start(graph, config, "Please reset my credentials")
    # Verify paused state and interrupt configuration
    assert pending(graph, config) == "clarification"
    snapshot = graph.get_state(config)
    assert "extract_fields" in snapshot.next
    assert snapshot.values["needs_clarification"] is True
    assert "application" in snapshot.values["clarification_question"]
    # Check that assistant question is queued
    assert result["messages"][-1]["role"] == "assistant"
    assert result["messages"][-1]["content"] == snapshot.values["clarification_question"]


def test_graph_pauses_at_approval_interrupt(graph):
    """Execution pauses at human_approval interrupt node before executing state-changing actions."""
    config = new_config()
    start(graph, config, "My ERP System password is locked out, please reset it")
    assert pending(graph, config) == "approval"
    snapshot = graph.get_state(config)
    assert "human_approval" in snapshot.next
    proposal = snapshot.values["action_proposal"]
    assert proposal.requires_approval is True
    assert proposal.status == ActionStatus.PENDING
    assert proposal.action_id not in nodes.EXECUTED_ACTION_IDS


def test_graph_resumes_cleanly_upon_clarification_reply(graph):
    """Workflow resumes upon user reply, updates state, and advances to subsequent nodes."""
    config = new_config()
    start(graph, config, "Please reset my password")
    assert pending(graph, config) == "clarification"

    # User replies with the missing application
    result = reply(graph, config, "The system is ERP System")
    assert result["extracted_fields"].application == "ERP System"
    assert result["needs_clarification"] is False
    # Next interrupt reached: human approval
    assert pending(graph, config) == "approval"
    assert result["action_proposal"].action_type == ActionType.RESET_CREDENTIALS


def test_graph_resumes_cleanly_upon_approval_decision(graph):
    """Workflow resumes upon operator decision, executes action, and produces final response."""
    config = new_config()
    start(graph, config, "My ERP System password is locked out, please reset it")
    assert pending(graph, config) == "approval"

    result = decide(graph, config, approved=True)
    assert pending(graph, config) is None
    assert result["action_proposal"].status == ActionStatus.EXECUTED
    assert result["action_proposal"].action_id in nodes.EXECUTED_ACTION_IDS
    assert "Action: reset_credentials [executed]" in result["final_response"]


def test_approved_action_executes_once(graph):
    config = new_config()
    start(graph, config, "My ERP System password is locked out, please reset it")
    assert pending(graph, config) == "approval"

    result = decide(graph, config, approved=True)
    assert pending(graph, config) is None
    assert result["action_proposal"].status == ActionStatus.EXECUTED
    assert result["action_proposal"].action_id in nodes.EXECUTED_ACTION_IDS


def test_rejected_action_is_not_executed(graph):
    config = new_config()
    start(graph, config, "My ERP System report export fails")
    assert graph.get_state(config).values["action_proposal"].action_type == ActionType.OPEN_TICKET

    result = decide(graph, config, approved=False)
    proposal = result["action_proposal"]
    assert proposal.status == ActionStatus.REJECTED
    assert proposal.action_id not in nodes.EXECUTED_ACTION_IDS
    assert "not approved" in result["final_response"]


def test_nothing_runs_before_approval(graph):
    config = new_config()
    start(graph, config, "My ERP System report export fails")
    proposal = graph.get_state(config).values["action_proposal"]
    assert proposal.status == ActionStatus.PENDING
    assert proposal.action_id not in nodes.EXECUTED_ACTION_IDS


def test_resume_after_restart_uses_checkpoint():
    """A new graph instance on the same checkpointer resumes the paused thread (restart)."""
    saver = MemorySaver()
    config = new_config()
    start(build_graph(saver), config, "My ERP System report export fails")

    restarted = build_graph(saver)
    assert pending(restarted, config) == "approval"
    result = decide(restarted, config, approved=True)
    assert result["action_proposal"].status == ActionStatus.EXECUTED


def test_execute_action_is_idempotent():
    proposal = ActionProposal(
        action_id=str(uuid.uuid4()),
        action_type=ActionType.OPEN_TICKET,
        status=ActionStatus.APPROVED,
        requires_approval=True,
    )
    first = nodes.execute_action(AgentState(action_proposal=proposal))["action_proposal"]
    # Same action_id arriving again (e.g. replay after a crash) must not run a second time.
    size = len(nodes.EXECUTED_ACTION_IDS)
    second = nodes.execute_action(AgentState(action_proposal=proposal))["action_proposal"]
    assert first.status == second.status == ActionStatus.EXECUTED
    assert len(nodes.EXECUTED_ACTION_IDS) == size


@requires_postgres
def test_graph_persists_durably_in_postgres_checkpoints_table():
    """State persists durably in PostgreSQL checkpoints & checkpoint_blobs tables ✋."""
    saver = PostgresSaver()
    graph = build_graph(saver)
    config = new_config()
    thread_id = config["configurable"]["thread_id"]

    start(graph, config, "Please reset my password")
    assert pending(graph, config) == "clarification"

    # Query Postgres database directly to confirm durable persistence
    with get_pooled_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM checkpoints WHERE thread_id = %s;",
                (thread_id,),
            )
            checkpoint_count = cur.fetchone()[0]
            assert checkpoint_count > 0, "Checkpoints must be recorded in Postgres checkpoints table"

            cur.execute(
                "SELECT COUNT(*) FROM checkpoint_blobs WHERE thread_id = %s;",
                (thread_id,),
            )
            blob_count = cur.fetchone()[0]
            assert blob_count > 0, "Channel blobs must be recorded in Postgres checkpoint_blobs table"


@requires_postgres
def test_graph_resumes_across_process_restart_with_postgres():
    """Graph resumes seamlessly across simulated process restarts using persistent PostgresSaver."""
    config = new_config()
    thread_id = config["configurable"]["thread_id"]

    # --- Process 1: Start workflow, interrupt at clarification ---
    g1 = build_graph(use_postgres=True)
    start(g1, config, "Please reset my password")
    assert pending(g1, config) == "clarification"
    del g1  # Simulate process termination

    # --- Process 2: Restart, reload state from Postgres, resume with user reply ---
    g2 = build_graph(use_postgres=True)
    assert pending(g2, config) == "clarification"
    res2 = reply(g2, config, "It is the ERP System")
    assert pending(g2, config) == "approval"
    assert res2["extracted_fields"].application == "ERP System"
    assert res2["action_proposal"].action_type == ActionType.RESET_CREDENTIALS
    del g2  # Simulate second process termination

    # --- Process 3: Restart again, reload state from Postgres, resume with operator approval ---
    g3 = build_graph(use_postgres=True)
    assert pending(g3, config) == "approval"
    res3 = decide(g3, config, approved=True)
    assert pending(g3, config) is None
    assert res3["action_proposal"].status == ActionStatus.EXECUTED
    assert "Action: reset_credentials [executed]" in res3["final_response"]


def test_build_graph_use_postgres_factory():
    """build_graph with use_postgres=True and get_production_graph initialize cleanly."""
    prod_graph = get_production_graph()
    assert prod_graph is not None

    pg_graph = build_graph(use_postgres=True)
    assert pg_graph is not None
