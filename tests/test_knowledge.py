"""Knowledge tests. Integration tests need DATABASE_URL / NEO4J_PASSWORD and a seeded stack."""
import json
import os

import pytest

from src.knowledge import ingest, seed_graph
from src.knowledge.common import pg
from src.knowledge.tools import check_graph, retrieve_policy

needs_pg = pytest.mark.skipif("DATABASE_URL" not in os.environ, reason="no Postgres")
needs_neo4j = pytest.mark.skipif("NEO4J_PASSWORD" not in os.environ, reason="no Neo4j")


# --- pure unit tests -------------------------------------------------------------------------
def test_every_policy_has_valid_front_matter():
    files = sorted(ingest.POLICIES.glob("*.md"))
    assert files
    for f in files:
        meta, body = ingest.parse(f)
        assert meta["doc_id"] and body


def test_chunk_packs_short_paragraphs_and_keeps_long_ones_whole():
    assert ingest.chunk("a\n\nb") == ["a\n\nb"]
    assert ingest.chunk("a\n\n" + "x" * 900) == ["a", "x" * 900]
    assert ingest.chunk("") == []


# --- integration: policies -------------------------------------------------------------------
@pytest.fixture(scope="module")
def stack():
    ingest.ingest()
    seed_graph.seed()


@needs_pg
def test_ingest_is_idempotent(stack):
    count = "SELECT count(*) FROM policy_chunks"
    with pg() as c:
        before = c.execute(count).fetchone()[0]
    ingest.ingest()
    with pg() as c:
        assert c.execute(count).fetchone()[0] == before


@needs_pg
def test_latest_version_wins_over_legacy(stack):
    r = retrieve_policy("I cannot log in, can you reset my password without checking outages?")
    assert (r.doc_id, str(r.effective_date)) == ("POL-001", "2026-09-01")  # v1 is 2024-03-15


@needs_pg
def test_future_dated_version_is_ignored(stack):
    with pg() as c:
        c.execute(
            "INSERT INTO policy_chunks SELECT doc_id, '2999-01-01', chunk_index, title, source,"
            " 'FUTURE', embedding FROM policy_chunks WHERE doc_id = 'POL-001' AND effective_date = '2026-09-01'"
        )
    try:
        assert str(retrieve_policy("password reset").effective_date) != "2999-01-01"
    finally:
        with pg() as c:
            c.execute("DELETE FROM policy_chunks WHERE effective_date = '2999-01-01'")


@needs_pg
def test_citations_for_eval_requests(stack):
    # Lexical fallback embeddings are weaker than OpenAI ones, so require a clear majority.
    items = json.loads((ingest.POLICIES.parent / "eval_dataset.json").read_text(encoding="utf-8"))
    cited = [i for i in items if i.get("expected_citation")]
    hits = sum(
        1 for i in cited
        if (r := retrieve_policy(i["request_text"]))
        and (r.doc_id, str(r.effective_date)) == tuple(i["expected_citation"].values())
    )
    assert hits / len(cited) >= 0.6, f"{hits}/{len(cited)} citations correct"


# --- integration: graph ----------------------------------------------------------------------
@needs_neo4j
def test_application_with_outage(stack):
    r = check_graph("Corporate VPN")
    assert r.found and "Identity Provider (SSO)" in r.dependencies
    assert [o.outage_id for o in r.active_outages] == ["OUT-2026-01"]


@needs_neo4j
def test_application_without_outage(stack):
    r = check_graph("ERP System")
    assert r.found and r.dependencies and r.active_outages == []


@needs_neo4j
def test_unknown_application(stack):
    assert not check_graph("Nonexistent App").found
    assert not check_graph("  ").found


@needs_neo4j
def test_seed_is_idempotent(stack):
    from src.knowledge.common import neo4j_driver

    def count():
        with neo4j_driver() as d:
            return d.execute_query("MATCH (n) OPTIONAL MATCH (n)-[r]->() RETURN count(DISTINCT n) + count(r)")[0][0][0]

    before = count()
    seed_graph.seed()
    assert count() == before
