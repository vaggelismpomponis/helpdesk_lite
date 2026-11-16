# Pinned Versions Policy: Docker Base Images & Python Dependencies

**Project:** HelpDesk Lite  
**Scope:** Docker Base Images, Python Dependencies, Container Environment Stability  
**Target Date:** 2026-11-16 (Day 1 Kick-off)  
**Status:** Agreed & Decided (All 5 Roles Aligned)  
**Primary Owner:** Platform Role  
**Related Documents:** [`CONTRIBUTING_LOG.md`](./CONTRIBUTING_LOG.md), [`COLLABORATION_GUIDE.md`](./COLLABORATION_GUIDE.md)

---

## 1. Motivation & Objectives

HelpDesk Lite is built by a distributed 5-person team across diverse host operating systems (Windows, macOS, Linux). To satisfy the core project milestone—**"The full stack boots up in <10 minutes on a clean clone on any laptop"**—all dependencies and container images must be deterministic.

Unpinned versions introduce silent build breakage, caching discrepancies, and API drift (e.g., minor version bumps in fast-moving libraries like LangChain or Chainlit). 

### Golden Rules
1. **Never use `:latest` or floating image tags.** Every Docker image must specify an exact, immutable tag.
2. **Never use loose dependency operators (`>=`, `~=`, `^`, unpinned).** Every Python package in `requirements.txt` must use exact equality (`==`).
3. **No unreviewed dependencies.** Any new package must be justified in a Pull Request and committed under the `deps` scope.

---

## 2. Docker Base Images Policy

All services configured in `Dockerfile` and `docker-compose.yml` must adhere to the pinned versions below:

| Service / Container | Pinned Base Image | Justification / Role |
|---|---|---|
| **App Service (Chainlit UI & Agent)** | `python:3.11-slim` | Debian-based slim Python 3.11 image. Provides minimal attack surface and small image size (~150MB), while retaining full compatibility with pre-built binary wheels for `psycopg[binary]`, `pgvector`, and `pydantic`. |
| **PostgreSQL + pgvector** | `pgvector/pgvector:pg16` | Official PostgreSQL 16 image bundled with pre-compiled `pgvector` extension. Guarantees vector similarity indexing (`vector` extension) is available on initial boot. |
| **Neo4j Graph Database** | `neo4j:5.26.0` | Official Neo4j Community Edition pinned to 5.26.0. Ensures Cypher syntax compatibility and driver stability with `neo4j==5.26.0`. |

### Docker Build Standards
- **Layer caching:** Copy `requirements.txt` and install dependencies *before* copying application code (`src/`, `data/`).
- **No byte-code clutter:** Set `ENV PYTHONDONTWRITEBYTECODE=1` and `ENV PYTHONUNBUFFERED=1`.
- **Clean package manager cache:** Always run `rm -rf /var/lib/apt/lists/*` after `apt-get install` to keep layers slim.

---

## 3. Python Dependencies Policy (`requirements.txt`)

All production, persistence, and test packages are pinned to exact versions in `requirements.txt`.

### Baseline Inventory

```text
# ==============================================================================
# Core Framework & Agent Workflow
# ==============================================================================
chainlit==1.3.2           # Interactive chat interface, steps, and approval cards
langgraph==0.2.45         # State graph orchestration, interrupts, checkpoints
langchain==0.3.7          # Composition and tool abstraction
langchain-core==0.3.15    # Core Pydantic primitives, messages, runnable protocols
langchain-community==0.3.7 # Community integrations
langchain-openai==0.2.6   # LLM runtime client

# ==============================================================================
# Persistence & Data Stores
# ==============================================================================
psycopg[binary,pool]==3.2.3 # PostgreSQL driver with connection pooling support
pgvector==0.3.6           # Python bindings for PostgreSQL vector extension
neo4j==5.26.0             # Official Neo4j Cypher driver

# ==============================================================================
# Settings, Validation & Environment
# ==============================================================================
pydantic==2.9.2           # High-performance data validation for contracts
pydantic-settings==2.6.1  # Environment variable parsing and configuration
python-dotenv==1.0.1      # Local development .env loader

# ==============================================================================
# Observability & Tracing
# ==============================================================================
langsmith==0.1.143        # Execution tracing, run metadata, evaluation dataset

# ==============================================================================
# Quality Assurance & Testing
# ==============================================================================
pytest==8.3.3             # Unit and integration test runner
pytest-asyncio==0.24.0    # Async test support for LangGraph and Chainlit
```

---

## 4. Dependency Change Management Protocol

To prevent dependency conflicts between roles, team members must follow this 4-step workflow:

```text
1. Propose in Stand-up  ──►  2. Update requirements.txt  ──►  3. Commit with scope 'deps'  ──►  4. Test Clean Install
   (Agree on necessity)        (Alphabetical & pinned)          feat(deps): add package          (<10 min verify)
```

1. **Stand-up Communication:** Announce in the daily stand-up before adding a dependency to avoid two members editing `requirements.txt` simultaneously.
2. **Alphabetical Sorting:** Keep entries grouped by domain and sorted alphabetically within their group to minimize diff collisions.
3. **Commit Scope:** Use the `deps` scope with conventional commit format:
   ```text
   feat(deps): pin pydantic-settings to 2.6.1
   ```
4. **Clean Verification:** Before opening a PR, test that `pip install --no-cache-dir -r requirements.txt` succeeds in a clean virtual environment or container.

---

## 5. Team Sign-off Matrix (Pinned Versions Policy)

| Role | Representative | Responsibility | Status | Date |
|---|---|---|---|---|
| **Platform** | @vaggelismpomponis | Docker base images, compose orchestration & OS portability | **Signed-off** | 2026-11-16 |
| **Workflow** | All members | LangGraph, LangChain Core & state checkpointer dependencies | **Signed-off** | 2026-11-16 |
| **Interface** | @AlexZarkalis | Chainlit UI library & websocket runtime | **Signed-off** | 2026-11-16 |
| **Knowledge** | @stef-fot | Neo4j driver, pgvector bindings & ingestion libraries | **Signed-off** | 2026-11-16 |
| **Quality** | @VickyMil-ai | Pytest, LangSmith SDK & evaluation dependencies | **Signed-off** | 2026-11-16 |
