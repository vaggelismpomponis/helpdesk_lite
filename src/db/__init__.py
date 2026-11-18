"""Database, Persistence and Idempotency package for HelpDesk Lite.

Platform Role | Scope: db, docker
"""

from src.db.checkpointer import PostgresSaver
from src.db.connection import (
    get_connection_pool,
    get_db_connection,
    get_db_url,
    get_pooled_connection,
)
from src.db.idempotency import (
    create_ticket_idempotent,
    execute_idempotent,
    get_action_status,
    is_action_executed,
    record_action,
)

__all__ = [
    "PostgresSaver",
    "get_db_url",
    "get_db_connection",
    "get_connection_pool",
    "get_pooled_connection",
    "record_action",
    "get_action_status",
    "is_action_executed",
    "execute_idempotent",
    "create_ticket_idempotent",
]
