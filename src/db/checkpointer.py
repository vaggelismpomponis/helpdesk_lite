"""PostgreSQL checkpoint saver for LangGraph (PostgresSaver).

Enables state persistence, interrupts, and seamless resumption across
process and application container restarts.
Adheres to architecture contracts (docs/ARCHITECTURE_CONTRACTS.md) and
the schema defined in docker/postgres/init.sql.

Platform Role | Scope: db, docker
"""

from __future__ import annotations

import asyncio
import json
from contextlib import AbstractAsyncContextManager, AbstractContextManager, contextmanager
from types import TracebackType
from typing import Any, AsyncIterator, Iterator, Optional, Sequence

import psycopg
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.serde.base import SerializerProtocol
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from src.db.connection import get_pooled_connection, get_db_connection


class PostgresSaver(
    BaseCheckpointSaver[str], AbstractContextManager, AbstractAsyncContextManager
):
    """PostgreSQL-backed checkpointer storing state in Postgres tables:
    - checkpoints
    - checkpoint_blobs
    - checkpoint_writes
    - checkpoint_migrations
    """

    def __init__(
        self,
        conn: Optional[psycopg.Connection] = None,
        *,
        serde: Optional[SerializerProtocol] = None,
    ) -> None:
        super().__init__(serde=serde or JsonPlusSerializer())
        self._external_conn = conn

    @contextmanager
    def _connection(self) -> Iterator[psycopg.Connection]:
        if self._external_conn is not None and not self._external_conn.closed:
            yield self._external_conn
        else:
            with get_pooled_connection() as conn:
                yield conn

    def __enter__(self) -> PostgresSaver:
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        pass

    async def __aenter__(self) -> PostgresSaver:
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.__exit__(exc_type, exc_val, exc_tb)

    def _load_blobs(
        self,
        conn: psycopg.Connection,
        thread_id: str,
        checkpoint_ns: str,
        versions: ChannelVersions,
    ) -> dict[str, Any]:
        channel_values: dict[str, Any] = {}
        if not versions:
            return channel_values

        with conn.cursor() as cur:
            for k, v in versions.items():
                cur.execute(
                    """
                    SELECT type, blob
                    FROM checkpoint_blobs
                    WHERE thread_id = %s
                      AND checkpoint_ns = %s
                      AND channel = %s
                      AND version = %s;
                    """,
                    (thread_id, checkpoint_ns, k, str(v)),
                )
                row = cur.fetchone()
                if row:
                    type_, blob = row
                    if type_ != "empty" and blob is not None:
                        channel_values[k] = self.serde.loads_typed(
                            (type_, bytes(blob) if isinstance(blob, memoryview) else blob)
                        )
        return channel_values

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Fetch a checkpoint tuple matching the provided config."""
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)

        with self._connection() as conn:
            with conn.cursor() as cur:
                if checkpoint_id:
                    cur.execute(
                        """
                        SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
                        FROM checkpoints
                        WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s;
                        """,
                        (thread_id, checkpoint_ns, checkpoint_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
                        FROM checkpoints
                        WHERE thread_id = %s AND checkpoint_ns = %s
                        ORDER BY checkpoint_id DESC
                        LIMIT 1;
                        """,
                        (thread_id, checkpoint_ns),
                    )
                row = cur.fetchone()
                if not row:
                    return None

                row_checkpoint_id, parent_checkpoint_id, type_, raw_checkpoint, raw_metadata = row

                checkpoint_: Checkpoint = (
                    raw_checkpoint
                    if isinstance(raw_checkpoint, dict)
                    else json.loads(raw_checkpoint)
                )
                metadata_: CheckpointMetadata = (
                    raw_metadata
                    if isinstance(raw_metadata, dict)
                    else json.loads(raw_metadata or "{}")
                )

                # Load channel values from checkpoint_blobs
                channel_values = self._load_blobs(
                    conn, thread_id, checkpoint_ns, checkpoint_.get("channel_versions", {})
                )

                # Load pending writes from checkpoint_writes
                cur.execute(
                    """
                    SELECT task_id, channel, type, blob
                    FROM checkpoint_writes
                    WHERE thread_id = %s AND checkpoint_ns = %s AND checkpoint_id = %s
                    ORDER BY idx ASC;
                    """,
                    (thread_id, checkpoint_ns, row_checkpoint_id),
                )
                writes_rows = cur.fetchall()
                pending_writes = [
                    (
                        task_id,
                        channel,
                        self.serde.loads_typed(
                            (w_type, bytes(blob) if isinstance(blob, memoryview) else blob)
                        ),
                    )
                    for task_id, channel, w_type, blob in writes_rows
                ]

                return CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": row_checkpoint_id,
                        }
                    },
                    checkpoint={**checkpoint_, "channel_values": channel_values},
                    metadata=metadata_,
                    pending_writes=pending_writes,
                    parent_config=(
                        {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": parent_checkpoint_id,
                            }
                        }
                        if parent_checkpoint_id
                        else None
                    ),
                )

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """List checkpoints matching the criteria, including metadata containment filter."""
        if not config:
            return

        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")

        query = """
            SELECT checkpoint_id
            FROM checkpoints
            WHERE thread_id = %s AND checkpoint_ns = %s
        """
        params: list[Any] = [thread_id, checkpoint_ns]

        # Apply JSONB metadata containment predicate matching other LangGraph checkpointers
        if filter:
            query += " AND metadata @> %s::jsonb"
            params.append(json.dumps(filter))

        if before:
            before_id = get_checkpoint_id(before)
            if before_id:
                query += " AND checkpoint_id < %s"
                params.append(before_id)

        query += " ORDER BY checkpoint_id DESC"
        if limit:
            query += f" LIMIT {int(limit)}"

        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        for (chk_id,) in rows:
            cfg = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": chk_id,
                }
            }
            res = self.get_tuple(cfg)
            if res:
                yield res

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Store checkpoint and channel blobs in PostgreSQL."""
        c = checkpoint.copy()
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")

        values: dict[str, Any] = c.pop("channel_values", {})

        with self._connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    # 1. Upsert blobs for new channel versions
                    for k, v in new_versions.items():
                        if k in values:
                            type_, blob_ = self.serde.dumps_typed(values[k])
                        else:
                            type_, blob_ = ("empty", b"")

                        cur.execute(
                            """
                            INSERT INTO checkpoint_blobs (thread_id, checkpoint_ns, channel, version, type, blob)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (thread_id, checkpoint_ns, channel, version)
                            DO UPDATE SET type = EXCLUDED.type, blob = EXCLUDED.blob;
                            """,
                            (thread_id, checkpoint_ns, k, str(v), type_, blob_),
                        )

                    # 2. Upsert checkpoint header
                    cur.execute(
                        """
                        INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                        ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id)
                        DO UPDATE SET
                            parent_checkpoint_id = EXCLUDED.parent_checkpoint_id,
                            checkpoint = EXCLUDED.checkpoint,
                            metadata = EXCLUDED.metadata;
                        """,
                        (
                            thread_id,
                            checkpoint_ns,
                            checkpoint_id,
                            parent_checkpoint_id,
                            "json",
                            json.dumps(c, default=str),
                            json.dumps(get_checkpoint_metadata(config, metadata), default=str),
                        ),
                    )

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store intermediate writes linked to a checkpoint."""
        thread_id = config["configurable"]["thread_id"]
        checkpoint_ns = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = config["configurable"]["checkpoint_id"]

        with self._connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    for idx, (channel, value) in enumerate(writes):
                        mapped_idx = WRITES_IDX_MAP.get(channel, idx)
                        type_, blob_ = self.serde.dumps_typed(value)
                        cur.execute(
                            """
                            INSERT INTO checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, blob, task_path)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                            DO UPDATE SET
                                channel = EXCLUDED.channel,
                                type = EXCLUDED.type,
                                blob = EXCLUDED.blob,
                                task_path = EXCLUDED.task_path;
                            """,
                            (
                                thread_id,
                                checkpoint_ns,
                                checkpoint_id,
                                task_id,
                                mapped_idx,
                                channel,
                                type_,
                                blob_,
                                task_path,
                            ),
                        )

    def delete_thread(self, thread_id: str) -> None:
        """Delete all checkpoints, blobs, and writes for a given thread_id."""
        with self._connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM checkpoints WHERE thread_id = %s;", (thread_id,))
                    cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id = %s;", (thread_id,))
                    cur.execute("DELETE FROM checkpoint_writes WHERE thread_id = %s;", (thread_id,))

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Asynchronous wrapper offloading blocking DB I/O to thread pool to protect event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get_tuple, config)

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """Asynchronous wrapper listing checkpoints without blocking event loop."""
        loop = asyncio.get_running_loop()
        items = await loop.run_in_executor(
            None, lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for item in items:
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Asynchronous wrapper saving checkpoint without blocking event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.put, config, checkpoint, metadata, new_versions
        )

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Asynchronous wrapper saving writes without blocking event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self.put_writes, config, writes, task_id, task_path
        )

    async def adelete_thread(self, thread_id: str) -> None:
        """Asynchronous wrapper deleting thread without blocking event loop."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.delete_thread, thread_id)
