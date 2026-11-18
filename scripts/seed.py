"""Automated Knowledge Ingestion and Neo4j Seeding Script.

Executed automatically as part of `docker compose up` via the `seed` service,
or directly via CLI:
    python scripts/seed.py
    docker compose run --rm seed

Idempotent: Re-running replaces policy chunks per version and MERGEs graph nodes.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure repo root is on Python path so src modules resolve cleanly
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Attempt to load .env if python-dotenv is present
try:
    from dotenv import load_dotenv

    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

from src.knowledge.common import neo4j_driver, pg
from src.knowledge.ingest import ingest
from src.knowledge.seed_graph import seed


def wait_for_services(max_attempts: int = 15, delay_seconds: float = 2.0) -> None:
    """Poll Postgres and Neo4j until both accept connections."""
    print("[Knowledge Seeding] ⏳ Checking database availability...")

    # 1. Postgres check
    pg_ready = False
    for attempt in range(1, max_attempts + 1):
        try:
            with pg() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    pg_ready = True
                    break
        except Exception as exc:
            print(
                f"[Knowledge Seeding] Waiting for PostgreSQL (attempt {attempt}/{max_attempts}): {exc}"
            )
            time.sleep(delay_seconds)

    if not pg_ready:
        raise RuntimeError(
            f"PostgreSQL connection failed after {max_attempts} attempts."
        )

    # 2. Neo4j check
    neo4j_ready = False
    for attempt in range(1, max_attempts + 1):
        try:
            with neo4j_driver() as driver:
                driver.verify_connectivity()
                neo4j_ready = True
                break
        except Exception as exc:
            print(
                f"[Knowledge Seeding] Waiting for Neo4j (attempt {attempt}/{max_attempts}): {exc}"
            )
            time.sleep(delay_seconds)

    if not neo4j_ready:
        raise RuntimeError(
            f"Neo4j connection failed after {max_attempts} attempts."
        )

    print("[Knowledge Seeding] ✅ PostgreSQL and Neo4j are reachable.")


def run_seeding(policies: bool = True, graph: bool = True) -> None:
    """Execute policy ingestion and Neo4j graph seeding."""
    print("=" * 70)
    print("HelpDesk Lite - Knowledge Ingestion & Graph Seeding")
    print("=" * 70)

    wait_for_services()

    if policies:
        print(
            "\n[1/2] 📄 Ingesting policies into PostgreSQL (pgvector)..."
        )
        doc_count = ingest()
        print(
            f"[1/2] ✅ Successfully ingested {doc_count} policy files into 'policy_chunks'."
        )

    if graph:
        print("\n[2/2] 🌐 Seeding Neo4j service dependency graph...")
        seed()
        print(
            "[2/2] ✅ Successfully seeded Neo4j graph (teams, employees, services, apps, outages)."
        )

    print("\n" + "=" * 70)
    print("🚀 Knowledge base ingestion and seeding completed successfully.")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed HelpDesk Lite PostgreSQL pgvector and Neo4j databases."
    )
    parser.add_argument(
        "--policies-only",
        action="store_true",
        help="Run only policy ingestion into PostgreSQL pgvector.",
    )
    parser.add_argument(
        "--graph-only",
        action="store_true",
        help="Run only Neo4j graph seeding.",
    )
    args = parser.parse_args()

    if args.policies_only and args.graph_only:
        parser.error(
            "Cannot specify both --policies-only and --graph-only simultaneously."
        )

    run_policies = not args.graph_only
    run_graph = not args.policies_only

    run_seeding(policies=run_policies, graph=run_graph)


if __name__ == "__main__":
    main()
