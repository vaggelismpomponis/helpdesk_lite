"""Day 5 Milestone Verification Suite: End-to-End Mock Workflow inside Docker Compose.

Validates Issue #27 deliverables (Workflow Role, Day 5 Milestone):
1. Validate that the entire LangGraph workflow runs end-to-end with mock nodes inside the
   Docker Compose environment.
2. Verify that no unhandled exceptions occur across all conditional paths and edge cases.
3. Ensure state persists durably in PostgresSaver checkpointer tables.

Reference: docs/roles/workflow.md (Step 7)
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from eval.dataset import load_examples
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
from src.agent.models import (
    ActionProposal,
    ActionStatus,
    ActionType,
    AgentState,
)
from src.db.checkpointer import PostgresSaver
from src.db.connection import get_pooled_connection, is_postgres_available

MARIA = "maria.papadopoulou@nimbus.com"
EMP02 = "employee02@nimbus.com"
# Office and device complete an incident request (POL-001: confirm them before acting).
AT_DESK = " I work from the Athens office on my MacBook Pro."

requires_postgres = pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL database not available at localhost:5432 / postgres:5432",
)


def new_config(email: str | None = MARIA) -> dict[str, Any]:
    return config_for(str(uuid.uuid4()), email)


# ==============================================================================
# 1. End-to-End Evaluation Dataset Runs (10 Scenarios inside Compose)
# ==============================================================================


@requires_postgres
def test_milestone_all_10_dataset_examples_run_e2e_in_compose():
    """Execute all 10 evaluation dataset examples through the production graph with PostgresSaver.

    Ensures every scenario completes without unhandled exceptions and reaches terminal END state.
    """
    examples = load_examples()
    assert len(examples) == 10, "Expected exactly 10 evaluation examples in dataset"

    # Use production graph with PostgresSaver persistence inside Compose
    graph = get_production_graph()

    for example in examples:
        example_id = example["metadata"]["id"]
        inputs = example["inputs"]
        expected = example["outputs"]

        config = config_for(str(uuid.uuid4()), inputs.get("sender_email"))
        request_text = inputs["request"]

        # Step 1: Start workflow
        state = start(graph, config, request_text)
        assert state is not None, f"[{example_id}] Start produced None state"

        # Step 2: Handle clarification interrupt if missing fields were flagged
        wait_reason = pending(graph, config)
        if wait_reason == "clarification":
            assert expected["asks_clarification"] is True, (
                f"[{example_id}] Graph paused for clarification unexpectedly"
            )
            clarification_reply = inputs.get("clarification_reply") or "I am using ERP System in Athens"
            state = reply(graph, config, clarification_reply)
            assert state is not None, f"[{example_id}] Reply produced None state"
            wait_reason = pending(graph, config)

        # Step 3: Handle approval interrupt if state-changing action requires approval
        if wait_reason == "approval":
            assert expected["requires_approval"] is True, (
                f"[{example_id}] Graph paused for approval unexpectedly"
            )
            decision = inputs.get("approval_decision", "approved")
            is_approved = decision == "approved"
            state = decide(graph, config, approved=is_approved)
            assert state is not None, f"[{example_id}] Decide produced None state"
            wait_reason = pending(graph, config)

        # Step 4: Verify terminal completion and output properties
        assert wait_reason is None, f"[{example_id}] Graph remained paused at {wait_reason}"
        proposal = state.get("action_proposal")
        assert proposal is not None, f"[{example_id}] Missing action_proposal"
        assert isinstance(proposal, ActionProposal), f"[{example_id}] Invalid action_proposal type"

        final_response = state.get("final_response")
        assert final_response and isinstance(final_response, str), (
            f"[{example_id}] Missing or empty final_response"
        )
        assert "Action:" in final_response, f"[{example_id}] Malformed final_response"


# ==============================================================================
# 2. Comprehensive Topology & Conditional Path Verification
# ==============================================================================


@requires_postgres
def test_path_clarification_to_approved_execution():
    """Path 1: Incomplete request -> ask_clarification -> user reply -> human_approval -> approved -> execute."""
    graph = get_production_graph()
    config = new_config()

    # Incomplete request (missing office and device)
    start(graph, config, "Please reset my credentials")
    assert pending(graph, config) == "clarification"
    snapshot = graph.get_state(config)
    assert snapshot.values["needs_clarification"] is True

    # User supplies the application, office and device
    reply(graph, config, "It is for ERP System." + AT_DESK)
    assert pending(graph, config) == "approval"
    proposal = graph.get_state(config).values["action_proposal"]
    assert proposal.action_type == ActionType.RESET_CREDENTIALS
    assert proposal.status == ActionStatus.PENDING

    # Operator approves
    result = decide(graph, config, approved=True)
    assert pending(graph, config) is None
    assert result["action_proposal"].status == ActionStatus.EXECUTED
    assert "Action: reset_credentials [executed]" in result["final_response"]


@requires_postgres
def test_path_clarification_to_rejected_execution():
    """Path 2: Incomplete request -> ask_clarification -> user reply -> human_approval -> rejected -> respond."""
    graph = get_production_graph()
    config = new_config()

    start(graph, config, "Please reset my password")
    assert pending(graph, config) == "clarification"

    reply(graph, config, "The system is ERP System." + AT_DESK)
    assert pending(graph, config) == "approval"

    # Operator rejects
    result = decide(graph, config, approved=False)
    assert pending(graph, config) is None
    assert result["action_proposal"].status == ActionStatus.REJECTED
    assert "not approved" in result["final_response"]


@requires_postgres
def test_path_direct_state_changing_approved():
    """Path 3: Complete request -> bypasses clarification -> human_approval -> approved -> execute."""
    graph = get_production_graph()
    config = new_config()

    start(graph, config, "My ERP System password is locked out, please reset it" + AT_DESK)
    assert pending(graph, config) == "approval"

    result = decide(graph, config, approved=True)
    assert pending(graph, config) is None
    assert result["action_proposal"].status == ActionStatus.EXECUTED


@requires_postgres
def test_path_direct_state_changing_rejected():
    """Path 4: Complete request -> bypasses clarification -> human_approval -> rejected -> respond."""
    graph = get_production_graph()
    config = new_config()

    start(graph, config, "The ERP System export fails with error 500" + AT_DESK)
    assert pending(graph, config) == "approval"

    result = decide(graph, config, approved=False)
    assert pending(graph, config) is None
    assert result["action_proposal"].status == ActionStatus.REJECTED
    assert "not approved" in result["final_response"]


@requires_postgres
def test_path_informational_policy_question():
    """Path 5: Policy question -> bypasses clarification and approval -> returns citation immediately."""
    graph = get_production_graph()
    config = new_config(EMP02)

    result = start(graph, config, "What is the Wi-Fi policy for visitors?")
    assert pending(graph, config) is None
    assert result["action_proposal"].action_type == ActionType.ANSWER_POLICY
    assert not result["action_proposal"].requires_approval
    assert result["policy_result"].doc_id == "POL-016"
    assert "POL-016 (effective 2026-01-05)" in result["final_response"]


@requires_postgres
def test_path_outage_detection_bypasses_approval():
    """Path 6: Request on application with active outage -> links to outage -> no approval needed."""
    graph = get_production_graph()
    config = new_config()

    result = start(graph, config, "I can't connect to the VPN, please reset my password" + AT_DESK)
    assert pending(graph, config) is None
    proposal = result["action_proposal"]
    assert proposal.action_type == ActionType.LINK_OUTAGE
    assert not proposal.requires_approval
    assert "open outage" in result["final_response"].lower()


@requires_postgres
def test_path_critical_incident_escalation():
    """Path 7: Critical keywords -> proposes escalate -> pauses for approval -> executes."""
    graph = get_production_graph()
    config = new_config()

    start(graph, config, "CRITICAL: ERP System production down and data breach risk" + AT_DESK)
    assert pending(graph, config) == "approval"
    proposal = graph.get_state(config).values["action_proposal"]
    assert proposal.action_type == ActionType.ESCALATE

    result = decide(graph, config, approved=True)
    assert pending(graph, config) is None
    assert result["action_proposal"].status == ActionStatus.EXECUTED


@requires_postgres
def test_path_idempotent_execution_protection():
    """Path 8: Duplicate execution replay is prevented without raising exceptions."""
    proposal = ActionProposal(
        action_id=str(uuid.uuid4()),
        action_type=ActionType.RESET_CREDENTIALS,
        status=ActionStatus.APPROVED,
        requires_approval=True,
    )
    state = AgentState(action_proposal=proposal)

    # First execution
    first_res = nodes.execute_action(state)["action_proposal"]
    assert first_res.status == ActionStatus.EXECUTED

    # Replay identical action_id
    second_res = nodes.execute_action(state)["action_proposal"]
    assert second_res.status == ActionStatus.EXECUTED
    assert second_res.action_id == first_res.action_id


# ==============================================================================
# 3. State Durability and Checkpoint Recovery in Compose
# ==============================================================================


@requires_postgres
def test_milestone_postgres_checkpoint_persistence_across_restarts():
    """Verify that multiple concurrent threads persist cleanly into PostgresSaver tables."""
    saver = PostgresSaver()
    graph_v1 = build_graph(saver)

    thread_1 = f"milestone_thread_1_{uuid.uuid4().hex[:8]}"
    thread_2 = f"milestone_thread_2_{uuid.uuid4().hex[:8]}"

    cfg_1 = config_for(thread_1, MARIA)
    cfg_2 = config_for(thread_2, MARIA)

    # Thread 1 stops at clarification
    start(graph_v1, cfg_1, "Please reset my password")
    assert pending(graph_v1, cfg_1) == "clarification"

    # Thread 2 stops at approval
    start(graph_v1, cfg_2, "My ERP System password is locked out, please reset it" + AT_DESK)
    assert pending(graph_v1, cfg_2) == "approval"

    # Directly check PostgreSQL checkpoints table
    with get_pooled_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM checkpoints WHERE thread_id IN (%s, %s);",
                (thread_1, thread_2),
            )
            count = cur.fetchone()[0]
            assert count >= 2, "Expected checkpoints for both threads in Postgres"

    # Simulate container/process restart: instantiate a new graph with fresh PostgresSaver
    saver_restart = PostgresSaver()
    graph_v2 = build_graph(saver_restart)

    # Thread 1 resumes from checkpoint
    assert pending(graph_v2, cfg_1) == "clarification"
    res_1 = reply(graph_v2, cfg_1, "The system is ERP System." + AT_DESK)
    assert pending(graph_v2, cfg_1) == "approval"

    # Thread 2 resumes from checkpoint
    assert pending(graph_v2, cfg_2) == "approval"
    res_2 = decide(graph_v2, cfg_2, approved=True)
    assert pending(graph_v2, cfg_2) is None
    assert res_2["action_proposal"].status == ActionStatus.EXECUTED
