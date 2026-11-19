"""Execution counting used by the restart scenario (eval/restart_scenario.py)."""

import uuid
import pytest

from eval.restart_scenario import REQUEST, SENDER, count_executions
from src.agent.graph import build_graph, config_for, decide, pending, start
from src.agent.models import ActionStatus
from src.db.checkpointer import PostgresSaver
from src.db.connection import get_pooled_connection, is_postgres_available

requires_postgres = pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL database not available at localhost:5432",
)


def test_counts_one_execution_and_ignores_replays():
    graph = build_graph()
    config = config_for(f"restart-{uuid.uuid4().hex[:8]}", SENDER)

    start(graph, config, REQUEST)
    assert pending(graph, config) == "approval"
    assert count_executions(graph, config) == 0

    decide(graph, config, approved=True)
    assert count_executions(graph, config) == 1

    graph.invoke(None, config)  # replay of the finished thread
    assert count_executions(graph, config) == 1


def test_rejected_action_counts_no_execution():
    graph = build_graph()
    config = config_for(f"restart-{uuid.uuid4().hex[:8]}", SENDER)
    start(graph, config, REQUEST)
    decide(graph, config, approved=False)
    assert count_executions(graph, config) == 0


def test_decide_guard_prevents_state_regression_on_finished_thread():
    """Verify decide() cannot regress status from executed to approved on finished threads."""
    graph = build_graph()
    config = config_for(f"restart-{uuid.uuid4().hex[:8]}", SENDER)

    start(graph, config, REQUEST)
    assert pending(graph, config) == "approval"

    res = decide(graph, config, approved=True)
    assert res["action_proposal"].status == ActionStatus.EXECUTED
    assert count_executions(graph, config) == 1

    # Calling decide() again on a finished thread must safely return without state regression
    res2 = decide(graph, config, approved=True)
    assert res2["action_proposal"].status == ActionStatus.EXECUTED, "Status must remain EXECUTED"
    assert count_executions(graph, config) == 1


@requires_postgres
def test_postgres_restart_scenario_end_to_end_zero_duplicates():
    """End-to-end verification of Step 11 / Issue #31 restart test with zero duplicate executions."""
    thread_id = f"restart-{uuid.uuid4().hex[:12]}"
    config = config_for(thread_id, SENDER)
    action_id = None

    try:
        # Phase 1: Start request requiring approval on PostgresSaver
        g1 = build_graph(use_postgres=True)
        res1 = start(g1, config, REQUEST)
        proposal1 = res1.get("action_proposal")
        action_id = proposal1.action_id

        assert pending(g1, config) == "approval"
        assert proposal1.status == ActionStatus.PENDING
        assert count_executions(g1, config) == 0

        # Verify audit_log pending status
        with get_pooled_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status, executed_at FROM audit_log WHERE action_id = %s;", (action_id,))
                row = cur.fetchone()
                assert row is not None
                assert row[0] == "pending"
                assert row[1] is None

        # Simulate Restart 1: Container / process crashes while waiting for approval
        del g1

        # Phase 2: Resume session after restart 1 -> must still be waiting for approval with 0 executions
        g2 = build_graph(use_postgres=True)
        assert pending(g2, config) == "approval", "Must survive restart 1 and remain paused for approval"
        assert count_executions(g2, config) == 0, "No execution should have occurred while paused"

        # Approve action -> must execute exactly once
        res2 = decide(g2, config, approved=True)
        assert res2["action_proposal"].status == ActionStatus.EXECUTED
        assert count_executions(g2, config) == 1

        # Verify audit_log is executed with timestamp
        with get_pooled_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status, executed_at FROM audit_log WHERE action_id = %s;", (action_id,))
                row = cur.fetchone()
                assert row is not None
                assert row[0] == "executed"
                assert row[1] is not None

        # Simulate Restart 2: Container / process crashes after execution
        del g2

        # Phase 3: Resume session after restart 2 -> must be completed, executed, with final response
        g3 = build_graph(use_postgres=True)
        assert pending(g3, config) is None, "Thread must be finished after restart 2"
        v3 = g3.get_state(config).values
        assert v3["action_proposal"].status == ActionStatus.EXECUTED
        assert bool(v3.get("final_response")), "Final response must be preserved"

        # Attempt replays on finished thread (e.g. network replay, double clicks, repeated decide)
        g3.invoke(None, config)
        decide(g3, config, approved=True)

        # Verification: Zero duplicate executions!
        final_executions = count_executions(g3, config)
        assert final_executions == 1, f"Expected exactly 1 execution, got {final_executions}"

        final_values = g3.get_state(config).values
        assert final_values["action_proposal"].status == ActionStatus.EXECUTED

        with get_pooled_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM audit_log WHERE action_id = %s;", (action_id,))
                assert cur.fetchone()[0] == 1, "Must have exactly one audit_log row"

    finally:
        PostgresSaver().delete_thread(thread_id)
        if action_id:
            with get_pooled_connection() as conn:
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM audit_log WHERE action_id = %s;", (action_id,))

