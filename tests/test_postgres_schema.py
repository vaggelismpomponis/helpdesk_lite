"""Tests for PostgreSQL initialization schema and contracts.

Validates that docker/postgres/init.sql includes all required extensions,
tables (tickets, audit_log, checkpoints, policy_chunks), columns, and indexes
agreed upon in Day 1 contracts and Issue #5.
"""

from pathlib import Path
import re
import unittest

INIT_SQL_PATH = Path(__file__).resolve().parent.parent / "docker" / "postgres" / "init.sql"
MIGRATION_SQL_PATH = (
    Path(__file__).resolve().parent.parent
    / "docker"
    / "postgres"
    / "migrations"
    / "001_upgrade_schema.sql"
)


class TestPostgresSchemaInit(unittest.TestCase):
    """Test suite for Postgres schema initialization script."""

    @classmethod
    def setUpClass(cls):
        cls.sql_path = INIT_SQL_PATH
        if not cls.sql_path.exists():
            raise FileNotFoundError(f"init.sql not found at {cls.sql_path}")
        cls.sql_content = cls.sql_path.read_text(encoding="utf-8")

    def test_init_sql_exists(self):
        self.assertTrue(self.sql_path.is_file())

    def test_pgvector_extension_enabled(self):
        pattern = r"CREATE\s+EXTENSION\s+IF\s+NOT\s+EXISTS\s+vector;"
        self.assertRegex(
            self.sql_content,
            pattern,
            "Postgres initialization must enable pgvector extension (CREATE EXTENSION IF NOT EXISTS vector)",
        )

    def test_tickets_table_and_columns(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS tickets", self.sql_content)
        expected_columns = [
            "id",
            "action_id",
            "employee",
            "application",
            "symptom",
            "urgency",
            "status",
            "details",
            "created_at",
            "updated_at",
        ]
        for col in expected_columns:
            self.assertRegex(
                self.sql_content,
                rf"\b{col}\b",
                f"tickets table missing column '{col}'",
            )

    def test_audit_log_table_and_columns(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS audit_log", self.sql_content)
        expected_columns = [
            "id",
            "action_id",
            "thread_id",
            "action_type",
            "status",
            "parameters",
            "rationale",
            "created_at",
            "executed_at",
        ]
        for col in expected_columns:
            self.assertRegex(
                self.sql_content,
                rf"\b{col}\b",
                f"audit_log table missing column '{col}'",
            )

    def test_langgraph_checkpoints_tables(self):
        tables = [
            "checkpoint_migrations",
            "checkpoints",
            "checkpoint_blobs",
            "checkpoint_writes",
        ]
        for table in tables:
            self.assertIn(
                f"CREATE TABLE IF NOT EXISTS {table}",
                self.sql_content,
                f"Missing LangGraph checkpointer table '{table}'",
            )

    def test_langgraph_checkpoints_columns(self):
        # checkpoints table core columns
        for col in ["thread_id", "checkpoint_ns", "checkpoint_id", "checkpoint", "metadata"]:
            self.assertRegex(
                self.sql_content,
                rf"\b{col}\b",
                f"checkpoints table missing column '{col}'",
            )

    def test_policy_chunks_table_and_columns(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS policy_chunks", self.sql_content)
        for col in ["doc_id", "title", "effective_date", "source", "content", "chunk_index", "embedding"]:
            self.assertRegex(
                self.sql_content,
                rf"\b{col}\b",
                f"policy_chunks table missing column '{col}'",
            )
        self.assertIn("vector(1536)", self.sql_content)

    def test_indexes_defined(self):
        expected_indexes = [
            "idx_tickets_action_id",
            "idx_tickets_employee",
            "idx_audit_log_action_id",
            "idx_audit_log_thread_id",
            "idx_checkpoints_thread_id",
            "idx_policy_doc_effective",
            "idx_policy_chunks_embedding",
        ]
        for idx in expected_indexes:
            self.assertIn(idx, self.sql_content, f"Missing index '{idx}'")


class TestPostgresUpgradeMigration(unittest.TestCase):
    """Test suite for non-destructive schema upgrade migration script."""

    @classmethod
    def setUpClass(cls):
        cls.sql_path = MIGRATION_SQL_PATH
        if not cls.sql_path.exists():
            raise FileNotFoundError(f"migration sql not found at {cls.sql_path}")
        cls.sql_content = cls.sql_path.read_text(encoding="utf-8")

    def test_migration_sql_exists(self):
        self.assertTrue(self.sql_path.is_file())

    def test_transaction_wrapped(self):
        self.assertRegex(
            self.sql_content,
            r"\bBEGIN\s*;",
            "Migration must be wrapped in a transaction starting with BEGIN;",
        )
        self.assertRegex(
            self.sql_content,
            r"\bCOMMIT\s*;",
            "Migration must commit the transaction with COMMIT;",
        )

    def test_tickets_column_alterations(self):
        self.assertRegex(
            self.sql_content,
            r"ALTER\s+TABLE\s+tickets\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+symptom\s+TEXT",
            "Migration must safely add symptom column with IF NOT EXISTS",
        )
        self.assertRegex(
            self.sql_content,
            r"ALTER\s+TABLE\s+tickets\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+urgency",
            "Migration must safely add urgency column with IF NOT EXISTS",
        )
        self.assertRegex(
            self.sql_content,
            r"ALTER\s+TABLE\s+tickets\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+details",
            "Migration must safely add details column with IF NOT EXISTS",
        )

    def test_backfill_before_not_null_enforcement(self):
        # Ensure backfill UPDATE occurs before ALTER COLUMN symptom SET NOT NULL
        backfill_pos = self.sql_content.find("UPDATE tickets")
        not_null_pos = self.sql_content.find("ALTER TABLE tickets ALTER COLUMN symptom SET NOT NULL")

        self.assertNotEqual(backfill_pos, -1, "Migration must backfill existing tickets")
        self.assertNotEqual(not_null_pos, -1, "Migration must enforce NOT NULL on symptom")
        self.assertLess(
            backfill_pos,
            not_null_pos,
            "Backfilling existing tickets must happen before enforcing symptom NOT NULL",
        )

    def test_audit_log_and_checkpoints_created(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS audit_log", self.sql_content)
        self.assertIn("CREATE TABLE IF NOT EXISTS checkpoints", self.sql_content)
        self.assertIn("CREATE TABLE IF NOT EXISTS checkpoint_blobs", self.sql_content)
        self.assertIn("CREATE TABLE IF NOT EXISTS checkpoint_writes", self.sql_content)
        self.assertIn("CREATE TABLE IF NOT EXISTS checkpoint_migrations", self.sql_content)

    def test_migration_indexes(self):
        expected_indexes = [
            "idx_tickets_action_id",
            "idx_tickets_employee",
            "idx_audit_log_action_id",
            "idx_audit_log_thread_id",
            "idx_checkpoints_thread_id",
            "idx_policy_chunks_embedding",
        ]
        for idx in expected_indexes:
            self.assertIn(idx, self.sql_content, f"Migration missing index '{idx}'")


if __name__ == "__main__":
    unittest.main()
