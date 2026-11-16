-- Initialization script for PostgreSQL + pgvector
-- Executed automatically on first container startup

CREATE EXTENSION IF NOT EXISTS vector;

-- Tickets table
CREATE TABLE IF NOT EXISTS tickets (
    id SERIAL PRIMARY KEY,
    action_id VARCHAR(64) UNIQUE NOT NULL,
    employee VARCHAR(128) NOT NULL,
    application VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Policy documents and vector embeddings table
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

