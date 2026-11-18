"""Idempotency guard and audit logging for state-changing operations.

Guarantees that state-changing actions (account resets, tickets, escalations)
are never executed more than once across container restarts, network replays,
or crash recovery.
Adheres to architecture contracts (docs/ARCHITECTURE_CONTRACTS.md) and
the schema defined in docker/postgres/init.sql.

Platform Role | Scope: db, docker
"""

from __future__ import annotations

import inspect
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
    Preserves terminal 'executed' status to prevent lifecycle regressions on conflict.
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
                        status = CASE
                            WHEN audit_log.status = 'executed' THEN 'executed'
                            ELSE EXCLUDED.status
                        END,
                        rationale = CASE
                            WHEN audit_log.status = 'executed' THEN audit_log.rationale
                            ELSE EXCLUDED.rationale
                        END,
                        parameters = CASE
                            WHEN audit_log.status = 'executed' THEN audit_log.parameters
                            ELSE EXCLUDED.parameters
                        END
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

    Guarantees:
    1. Short-circuits if status is already 'executed', preventing duplicate side effects.
    2. Rejects any status other than 'approved' (e.g. 'pending', 'rejected'), ensuring
       unapproved actions are never invoked.
    3. Serializes execution using PostgreSQL row-level locking (SELECT ... FOR UPDATE).
    4. Downstream operations are passed action_id to enable durable downstream idempotency.

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

                current_status = row["status"]

                if current_status == "executed":
                    # Already executed, skip execution safely
                    return False, "already_executed"

                if current_status != "approved":
                    raise ValueError(
                        f"Action '{action_id}' cannot be executed with status '{current_status}'. "
                        "State-changing actions require explicit human approval."
                    )

                # Pass action_id to execution_fn if supported by its signature for downstream idempotency
                sig = inspect.signature(execution_fn)
                if "action_id" in sig.parameters and "action_id" not in kwargs:
                    kwargs["action_id"] = action_id

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
    """Idempotently insert an IT support ticket into tickets table in a single atomic operation.

    Uses INSERT ... ON CONFLICT (action_id) DO NOTHING to eliminate race conditions
    between concurrent workers.

    Returns:
        (created, ticket_record):
            - (True, record) if newly created.
            - (False, record) if already existed.
    """
    details_json = json.dumps(details or {})
    with get_pooled_connection() as conn:
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO tickets (
                        action_id, employee, application, symptom, urgency, status, details
                    )
                    VALUES (%s, %s, %s, %s, %s, 'pending', %s::jsonb)
                    ON CONFLICT (action_id) DO NOTHING
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
                inserted = cur.fetchone()
                if inserted:
                    return True, inserted

                # Conflict occurred; fetch the pre-existing row atomically
                cur.execute(
                    "SELECT * FROM tickets WHERE action_id = %s;",
                    (action_id,),
                )
                existing = cur.fetchone()
                return False, existing
