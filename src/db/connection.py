"""PostgreSQL connection management and connection pooling for HelpDesk Lite.

Platform Role | Scope: db, docker
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Generator, Optional

import psycopg
from psycopg_pool import ConnectionPool


def get_db_url() -> str:
    """Return configured PostgreSQL connection URL."""
    url = os.getenv("DATABASE_URL")
    if not url:
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        user = os.getenv("POSTGRES_USER", "postgres")
        pw = os.getenv("POSTGRES_PASSWORD", "postgres_secure_password")
        db = os.getenv("POSTGRES_DB", "helpdesk")
        url = f"postgresql://{user}:{pw}@{host}:{port}/{db}"
    return url


_POOL: Optional[ConnectionPool] = None
_POOL_LOCK = threading.Lock()


def get_connection_pool(min_size: int = 1, max_size: int = 10) -> ConnectionPool:
    """Get or create singleton connection pool for multi-threaded checkpointer access."""
    global _POOL
    if _POOL is None or _POOL.closed:
        with _POOL_LOCK:
            if _POOL is None or _POOL.closed:
                _POOL = ConnectionPool(
                    conninfo=get_db_url(),
                    min_size=min_size,
                    max_size=max_size,
                    open=True,
                )
    return _POOL


def get_db_connection(row_factory: Optional[any] = None) -> psycopg.Connection:
    """Create a standalone PostgreSQL connection using environment configuration."""
    kwargs = {}
    if row_factory:
        kwargs["row_factory"] = row_factory
    return psycopg.connect(get_db_url(), **kwargs)


@contextmanager
def get_pooled_connection() -> Generator[psycopg.Connection, None, None]:
    """Borrow a connection from the pool and return it upon block exit."""
    pool = get_connection_pool()
    with pool.connection() as conn:
        yield conn
