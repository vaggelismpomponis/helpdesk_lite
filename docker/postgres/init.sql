-- ==============================================================================
-- HelpDesk Lite: PostgreSQL + pgvector Initialization Script
-- Executed automatically on initial container startup (/docker-entrypoint-initdb.d)
-- Scope: db | Platform Role | Target: Issue #5
-- ==============================================================================

-- 1. Enable pgvector extension for semantic policy search
CREATE EXTENSION IF NOT EXISTS vector;

-- ==============================================================================
-- 2. IT Support Tickets Table
-- Tracks state-changing ticket creation requests (ActionType.OPEN_TICKET)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS tickets (
    id SERIAL PRIMARY KEY,
    action_id VARCHAR(64) UNIQUE NOT NULL,
    employee VARCHAR(128) NOT NULL,
    application VARCHAR(128) NOT NULL,
    symptom TEXT NOT NULL,
    urgency VARCHAR(32) NOT NULL DEFAULT 'medium',
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    details JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tickets_action_id ON tickets(action_id);
CREATE INDEX IF NOT EXISTS idx_tickets_employee ON tickets(employee);
CREATE INDEX IF NOT EXISTS idx_tickets_application ON tickets(application);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

-- ==============================================================================
-- 3. Audit Log Table
-- Audit trail and idempotency guard for all proposed and executed actions
-- Guarantees state-changing operations are not executed twice upon restart
-- ==============================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    action_id VARCHAR(64) UNIQUE NOT NULL,
    thread_id VARCHAR(128) NOT NULL,
    action_type VARCHAR(64) NOT NULL,
    employee VARCHAR(128),
    application VARCHAR(128),
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    parameters JSONB DEFAULT '{}',
    rationale TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    executed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_audit_log_action_id ON audit_log(action_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_thread_id ON audit_log(thread_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_status ON audit_log(status);

-- ==============================================================================
-- 4. LangGraph Checkpoints (PostgresSaver)
-- Supports state serialization, interrupts, human approval, and resume on restart
-- Standard schema utilized by langgraph-checkpoint-postgres
-- ==============================================================================
CREATE TABLE IF NOT EXISTS checkpoint_migrations (
    v INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    task_path TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_id ON checkpoints(thread_id);
CREATE INDEX IF NOT EXISTS idx_checkpoint_blobs_thread_id ON checkpoint_blobs(thread_id);
CREATE INDEX IF NOT EXISTS idx_checkpoint_writes_thread_id ON checkpoint_writes(thread_id);

-- ==============================================================================
-- 5. Policy Chunks & Vector Store (Knowledge Role)
-- Stores policy document embeddings with metadata for latest effective date resolution
-- Primary key: (doc_id, effective_date, chunk_index)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS policy_chunks (
    doc_id VARCHAR(64) NOT NULL,
    effective_date DATE NOT NULL,
    chunk_index INTEGER NOT NULL,
    title VARCHAR(255) NOT NULL,
    source VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    PRIMARY KEY (doc_id, effective_date, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_policy_doc_effective ON policy_chunks(doc_id, effective_date DESC);
CREATE INDEX IF NOT EXISTS idx_policy_chunks_embedding ON policy_chunks USING hnsw (embedding vector_cosine_ops);
