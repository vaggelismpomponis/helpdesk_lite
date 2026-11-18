"""Idempotency guard and audit logging for state-changing operations.

Guarantees that state-changing actions (account resets, tickets, escalations)
are never executed more than once across container restarts, network replays,
or crash recovery.
Adheres to architecture contracts (docs/ARCHITECTURE_CONTRACTS.md) and
the schema defined in docker/postgres/init.sql.

Platform Role | Scope: db, docker
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Optional, Tuple

import psycopg
from psycopg.rows import dict_row

from src.db.connection import get_pooled_connection


def record_action(
    action_id: str,
    thread_id: str,
    action_type: str,
    employee: Optional[str] = None,
    application: Optional[str] = None,
    status: str = "pending",
    parameters: Optional[Dict[str, Any]] = None,
    rationale: str = "",
) -> Dict[str, Any]:
    """Record or update an action proposal in audit_log.

    Guarantees unique action_id tracking per Day 1 contracts.
    """
    params_json = json.dumps(parameters or {})
    with get_pooled_connection() as conn:
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log (
                        action_id, thread_id, action_type, employee, application,
                        status, parameters, rationale
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (action_id)
                    DO UPDATE SET
                        status = EXCLUDED.status,
                        rationale = EXCLUDED.rationale,
                        parameters = EXCLUDED.parameters
                    RETURNING *;
                    """,
                    (
                        action_id,
                        thread_id,
                        action_type,
                        employee,
                        application,
                        status,
                        params_json,
                        rationale,
                    ),
                )
                return cur.fetchone()


def get_action_status(action_id: str) -> Optional[str]:
    """Retrieve the current lifecycle status of an action."""
    with get_pooled_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM audit_log WHERE action_id = %s;",
                (action_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None


def is_action_executed(action_id: str) -> bool:
    """Check if the action has already been executed."""
    status = get_action_status(action_id)
    return status == "executed"


def execute_idempotent(
    action_id: str,
    execution_fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Tuple[bool, Any]:
    """Atomically execute an action proposal with strict idempotency guard.

    Uses row-level locking (SELECT ... FOR UPDATE) in PostgreSQL to ensure
    concurrent workers or recovered containers do not execute the same action twice.

    Returns:
        (executed, result):
            - (True, result) if action was executed in this call.
            - (False, "already_executed") if action was already completed previously.
    """
    with get_pooled_connection() as conn:
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT status FROM audit_log WHERE action_id = %s FOR UPDATE;",
                    (action_id,),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Action '{action_id}' not found in audit_log")

                if row["status"] == "executed":
                    # Already executed, skip execution safely
                    return False, "already_executed"

                # Run the state-changing action
                result = execution_fn(*args, **kwargs)

                # Mark as executed atomically with timestamp
                cur.execute(
                    """
                    UPDATE audit_log
                    SET status = 'executed',
                        executed_at = CURRENT_TIMESTAMP
                    WHERE action_id = %s;
                    """,
                    (action_id,),
                )
                return True, result


def create_ticket_idempotent(
    action_id: str,
    employee: str,
    application: str,
    symptom: str,
    urgency: str = "medium",
    details: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """Idempotently insert an IT support ticket into tickets table.

    If a ticket with action_id already exists, returns the existing record
    without duplicating.

    Returns:
        (created, ticket_record):
            - (True, record) if newly created.
            - (False, record) if already existed.
    """
    details_json = json.dumps(details or {})
    with get_pooled_connection() as conn:
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                # Check existing
                cur.execute(
                    "SELECT * FROM tickets WHERE action_id = %s;",
                    (action_id,),
                )
                existing = cur.fetchone()
                if existing:
                    return False, existing

                cur.execute(
                    """
                    INSERT INTO tickets (
                        action_id, employee, application, symptom, urgency, status, details
                    )
                    VALUES (%s, %s, %s, %s, %s, 'pending', %s::jsonb)
                    RETURNING *;
                    """,
                    (
                        action_id,
                        employee,
                        application,
                        symptom,
                        urgency,
                        details_json,
                    ),
                )
                return True, cur.fetchone()
