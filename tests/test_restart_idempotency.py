"""Integration and verification test suite for Container Restart Support and Idempotency Guard.

Validates Issue #9 deliverables (Platform Role, Days 6-10 Completion):
1. Support app container restart testing without volume or state corruption.
2. Verify that state persists in Postgres and Neo4j across `docker compose restart app`
   or `docker compose down && docker compose up`.
3. Verify persistent Postgres checkpoints (PostgresSaver) across container recovery.
4. Verify approved actions do not re-execute upon container restart/recovery.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml

from langgraph.checkpoint.base import CheckpointTuple
from langgraph.graph import END, START, StateGraph

from src.db.checkpointer import PostgresSaver
from src.db.connection import get_pooled_connection
from src.db.idempotency import (
    create_ticket_idempotent,
    execute_idempotent,
    is_action_executed,
    record_action,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def is_postgres_available() -> bool:
    """Check if PostgreSQL is reachable."""
    try:
        with get_pooled_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                return True
    except Exception:
        return False


# Skip tests requiring live PostgreSQL if service is not running
requires_postgres = pytest.mark.skipif(
    not is_postgres_available(),
    reason="Live PostgreSQL database not available at localhost:5432",
)


def test_compose_volumes_and_restart_policy():
    """Verify docker-compose.yml defines persistent volumes and resilient restart policies."""
    compose_path = REPO_ROOT / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist"

    data = yaml.safe_load(compose_path.read_text())
    services = data.get("services", {})

    # 1. Named volume definitions
    volumes = data.get("volumes", {})
    assert "postgres_data" in volumes, "postgres_data must be defined as a persistent volume"
    assert "neo4j_data" in volumes, "neo4j_data must be defined as a persistent volume"

    # 2. Service mount points
    assert any("postgres_data:" in str(v) for v in services["postgres"].get("volumes", []))
    assert any("neo4j_data:" in str(v) for v in services["neo4j"].get("volumes", []))

    # 3. Restart and graceful shutdown settings
    app = services["app"]
    assert app.get("restart") == "unless-stopped", "app service must restart unless stopped"
    assert app.get("stop_grace_period") == "15s", "app service must allow 15s graceful shutdown"

    seed = services["seed"]
    assert seed.get("restart") == "no", "seed service must not restart continuously"


@requires_postgres
def test_postgres_checkpointer_saves_and_recovers_state():
    """Verify PostgresSaver persists graph state across simulated process/container restart."""
    thread_id = f"test_restart_{uuid.uuid4().hex[:12]}"

    # Define a stateful workflow with an interrupt before the second step
    builder = StateGraph(dict)
    builder.add_node("step_triage", lambda s: {"status": "waiting_approval", "action": "reset_pwd"})
    builder.add_node("step_execute", lambda s: {"status": "executed", "action": "reset_pwd"})
    builder.add_edge(START, "step_triage")
    builder.add_edge("step_triage", "step_execute")
    builder.add_edge("step_execute", END)

    saver = PostgresSaver()
    graph_v1 = builder.compile(checkpointer=saver, interrupt_before=["step_execute"])
    config = {"configurable": {"thread_id": thread_id}}

    try:
        # Step 1: Run until interrupt (approval paused)
        graph_v1.invoke({"status": "initial"}, config)

        paused_state = graph_v1.get_state(config)
        assert paused_state.next == ("step_execute",), "Graph must pause before step_execute"
        assert paused_state.values["status"] == "waiting_approval"

        # Step 2: Simulate container crash/restart by completely deleting the in-memory graph
        del graph_v1
        del saver

        # Step 3: Re-instantiate a brand new graph instance connected to PostgreSQL (container recovery)
        new_saver = PostgresSaver()
        graph_v2 = builder.compile(checkpointer=new_saver, interrupt_before=["step_execute"])

        recovered_state = graph_v2.get_state(config)
        assert recovered_state is not None, "State must be recovered from Postgres checkpoints"
        assert recovered_state.next == ("step_execute",), "Recovered state must resume at exact interrupt"
        assert recovered_state.values["status"] == "waiting_approval"
        assert recovered_state.values["action"] == "reset_pwd"

        # Step 4: Resume execution to completion
        final_result = graph_v2.invoke(None, config)
        assert final_result["status"] == "executed"

        completed_state = graph_v2.get_state(config)
        assert completed_state.next == ()
        assert completed_state.values["status"] == "executed"

    finally:
        PostgresSaver().delete_thread(thread_id)


@requires_postgres
def test_idempotency_prevents_duplicate_execution_on_container_recovery():
    """Verify approved actions do not re-execute upon container recovery or duplicate invocation."""
    action_id = f"act_{uuid.uuid4().hex[:16]}"
    thread_id = f"thread_{uuid.uuid4().hex[:12]}"

    # Record action in audit log
    record = record_action(
        action_id=action_id,
        thread_id=thread_id,
        action_type="reset_credentials",
        employee="test.user@nimbus.com",
        application="Finance Portal",
        status="approved",
        parameters={"scope": "mfa_reset"},
        rationale="Manager approved ticket",
    )
    assert record["status"] == "approved"
    assert record["action_id"] == action_id

    execution_count = 0

    def mock_external_api_call():
        nonlocal execution_count
        execution_count += 1
        return {"result": "credential_reset_success"}

    try:
        # 1. Initial execution
        executed, res = execute_idempotent(action_id, mock_external_api_call)
        assert executed is True, "First call should execute the action"
        assert res["result"] == "credential_reset_success"
        assert execution_count == 1
        assert is_action_executed(action_id) is True

        # 2. Simulate container recovery / message replay triggering execute again
        executed_second, res_second = execute_idempotent(action_id, mock_external_api_call)
        assert executed_second is False, "Second call must NOT execute the action"
        assert res_second == "already_executed"
        assert execution_count == 1, "Side effect count must remain strictly 1"

    finally:
        with get_pooled_connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM audit_log WHERE action_id = %s;", (action_id,))


@requires_postgres
def test_ticket_idempotency_prevents_duplicate_ticket_creation():
    """Verify creating a ticket with an existing action_id does not duplicate records."""
    action_id = f"ticket_act_{uuid.uuid4().hex[:16]}"

    try:
        # 1. Create first ticket
        created1, ticket1 = create_ticket_idempotent(
            action_id=action_id,
            employee="test.user@nimbus.com",
            application="ERP System",
            symptom="Database connection timeout error 500",
            urgency="high",
            details={"env": "prod"},
        )
        assert created1 is True
        assert ticket1["action_id"] == action_id
        ticket_id = ticket1["id"]

        # 2. Re-attempt ticket creation with identical action_id (e.g. after container restart)
        created2, ticket2 = create_ticket_idempotent(
            action_id=action_id,
            employee="test.user@nimbus.com",
            application="ERP System",
            symptom="Database connection timeout error 500",
            urgency="high",
            details={"env": "prod"},
        )
        assert created2 is False, "Duplicate ticket creation must be rejected"
        assert ticket2["id"] == ticket_id, "Must return original ticket record without duplicate"

        # Verify exactly one record in database
        with get_pooled_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM tickets WHERE action_id = %s;", (action_id,))
                count = cur.fetchone()[0]
                assert count == 1, "There must be exactly one ticket for this action_id"

    finally:
        with get_pooled_connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM tickets WHERE action_id = %s;", (action_id,))


@requires_postgres
def test_seed_rerun_preserves_checkpoints_and_tickets():
    """Verify that automated seeding (which re-runs on docker compose up) does not wipe session state."""
    thread_id = f"preserve_test_{uuid.uuid4().hex[:12]}"
    action_id = f"preserve_act_{uuid.uuid4().hex[:16]}"

    saver = PostgresSaver()
    saver.put(
        {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}},
        {"id": "chk_test_1", "v": 1, "ts": "2026-11-18T00:00:00Z", "channel_versions": {}, "channel_values": {"msg": "hello"}},
        {"source": "test"},
        {},
    )
    record_action(action_id, thread_id, "answer_policy", status="executed")

    try:
        # Execute seeding logic
        from scripts.seed import run_seeding

        run_seeding(policies=True, graph=False)

        # Verify checkpoint is still intact
        tup = saver.get_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
        assert tup is not None, "Checkpoints must survive compose seeding"
        assert tup.checkpoint["id"] == "chk_test_1"

        # Verify audit_log is still intact
        assert is_action_executed(action_id) is True, "Audit log must survive compose seeding"

    finally:
        saver.delete_thread(thread_id)
        with get_pooled_connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM audit_log WHERE action_id = %s;", (action_id,))
