-- ==============================================================================
-- HelpDesk Lite: PostgreSQL Database Schema Upgrade Migration
-- File: docker/postgres/migrations/001_upgrade_schema.sql
-- Target: Issue #5 / PR #67
--
-- Non-destructive upgrade migration for existing PostgreSQL volumes (postgres_data).
-- Upgrades tables, backfills existing data, applies NOT NULL constraints,
-- and adds audit logging, LangGraph checkpoints, and vector indexes.
-- ==============================================================================

BEGIN;

-- 1. Ensure pgvector extension is enabled
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Upgrade 'tickets' table schema
-- Ensure base table exists if running on a fresh database
CREATE TABLE IF NOT EXISTS tickets (
    id SERIAL PRIMARY KEY,
    action_id VARCHAR(64) UNIQUE NOT NULL,
    employee VARCHAR(128) NOT NULL,
    application VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Add new columns if missing from earlier schema version
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS symptom TEXT;
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS urgency VARCHAR(32) DEFAULT 'medium';
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS details JSONB DEFAULT '{}';

-- Backfill existing tickets missing symptom or urgency before enforcing NOT NULL
UPDATE tickets
SET symptom = 'Unspecified symptom (migrated ticket)'
WHERE symptom IS NULL;

UPDATE tickets
SET urgency = 'medium'
WHERE urgency IS NULL;

UPDATE tickets
SET details = '{}'
WHERE details IS NULL;

-- Enforce NOT NULL constraints and defaults on backfilled columns
ALTER TABLE tickets ALTER COLUMN symptom SET NOT NULL;
ALTER TABLE tickets ALTER COLUMN urgency SET NOT NULL;
ALTER TABLE tickets ALTER COLUMN urgency SET DEFAULT 'medium';
ALTER TABLE tickets ALTER COLUMN details SET DEFAULT '{}';

-- Create missing indexes on 'tickets'
CREATE INDEX IF NOT EXISTS idx_tickets_action_id ON tickets(action_id);
CREATE INDEX IF NOT EXISTS idx_tickets_employee ON tickets(employee);
CREATE INDEX IF NOT EXISTS idx_tickets_application ON tickets(application);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

-- ==============================================================================
-- 3. Audit Log Table (Idempotency Guard & Audit Trail)
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
-- 5. Policy Chunks & Vector Store
-- ==============================================================================
CREATE TABLE IF NOT EXISTS policy_chunks (
    id SERIAL PRIMARY KEY,
    doc_id VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    effective_date DATE NOT NULL,
    source VARCHAR(255) NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector(1536)
);

CREATE INDEX IF NOT EXISTS idx_policy_doc_effective ON policy_chunks(doc_id, effective_date DESC);
CREATE INDEX IF NOT EXISTS idx_policy_chunks_embedding ON policy_chunks USING hnsw (embedding vector_cosine_ops);

COMMIT;
