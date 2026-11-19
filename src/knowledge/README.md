# Knowledge

Data and tools the agent uses to answer: **policies** (Postgres + pgvector) and the **service
dependency graph** (Neo4j). Workflow calls the two tools below and never touches the databases.

## Tools (`tools.py`)

| Tool | Returns | Rule |
|---|---|---|
| `retrieve_policy(query, application=None)` | `PolicyResult` (`text`, `doc_id`, `effective_date`, `source`) or `None` | Per `doc_id` the **newest `effective_date` (not in the future) wins**, then the best match by vector similarity. An old version never outranks the current one. |
| `check_graph(application)` | `GraphResult` (`dependencies`, `active_outages`, `found`, `outages`) | Parameterized Cypher: `Application -DEPENDS_ON-> Service -HAS_OUTAGE-> Outage {status: 'OPEN'}`. Unknown app gives `found=False`. |

Output models are in `models.py` (contract: `docs/ARCHITECTURE_CONTRACTS.md`).
`mocks.py` has the same signatures with fixed data, for tests that need no database.

## Data (`src/data/`)

- `policies/*.md`: 20 policies with front matter (`doc_id`, `title`, `effective_date`). `POL-001` has two versions (v1, v2) to exercise version resolution.
- `graph_seed.json`: teams, employees, services, applications, outages.
- `eval_dataset.json`: the 10 evaluation requests (see `docs/KNOWLEDGE_HANDOFF.md`).

## Loading the data (both idempotent)

```
docker compose run --rm seed          # ingest + graph seed, inside compose
python -m src.knowledge.ingest        # policies -> pgvector (replaces chunks per version)
python -m src.knowledge.seed_graph    # graph -> Neo4j (MERGE on ids)
```

Graph model: `docs/KNOWLEDGE_GRAPH.md`. Table: `policy_chunks` in `docker/postgres/init.sql`
(primary key `doc_id, effective_date, chunk_index`).

## Config (environment)

`DATABASE_URL` (or `POSTGRES_*`), `NEO4J_URI`/`NEO4J_USER`/`NEO4J_PASSWORD`, and for embeddings
`AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
(or `OPENAI_API_KEY`). Without a working key, or with `OFFLINE_MODE=true`, embeddings fall back to
a lexical hash: fine for dev and tests, weaker than real embeddings. Re-run ingest after changing it.

## Tests

`python -m unittest discover tests` (`tests/test_knowledge.py` needs the databases running).
