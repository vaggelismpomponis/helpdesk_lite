# CONTRIBUTING Log

Τρέχον αρχείο αποφάσεων για το `CONTRIBUTING.md` (team agreement). Ο Quality το συντηρεί και περνά τις **Αποφασισμένες** εγγραφές στο `CONTRIBUTING.md`. Όταν το `CONTRIBUTING.md` γίνει final, το log μένει ως ιστορικό.

## Πώς το γεμίζουμε

1. Κάθε απόφαση ή αλλαγή κανόνα γίνεται **νέα γραμμή** στο [Log αποφάσεων](#log-αποφάσεων) την ίδια μέρα (πιο πρόσφατη στο τέλος).
2. Αν αφορά ένα θέμα του [Πίνακα θεμάτων](#πίνακας-θεμάτων-για-το-contributingmd), ενημερώνεται και η γραμμή του (status, απόφαση).
3. Κάθε γραμμή έχει πηγή: συνάντηση, PR ή issue.
4. Το log αλλάζει μέσω PR με prefix `docs(...)`, όπως κάθε αρχείο.

## Πίνακας θεμάτων για το CONTRIBUTING.md

Status: `Proposed` (προτάθηκε) · `Decided` (συμφωνήθηκε) · `In CONTRIBUTING` (έχει περαστεί).

| # | Θέμα | Απόφαση / Πρόταση | Status | Πηγή |
|---|---|---|---|---|
| 1 | Branch strategy | `main` (release) και `develop` (integration), προστατευμένα. Feature branches `feature/`, `bugfix/`, `hotfix/`, `docs/` από `develop`. | Proposed | [AGENTS.md](../AGENTS.md), [GIT_GUIDE](./GIT_GUIDE.md) |
| 2 | Κανόνας PR | PR → `develop`, ≥1 reviewer, όχι self-merge, <300 γραμμές, review <24 ώρες. | Proposed | [README](../README.md#working-agreements) |
| 3 | Merge method | Squash στο `develop`. Merge commit για release `develop` → `main`. | Proposed | [AGENTS.md](../AGENTS.md) |
| 4 | Commit convention | Conventional Commits 1.0.0, scopes: `graph`, `ui`, `policy`, `neo4j`, `db`, `approval`, `eval`, `docker`, `docs`, `deps`. | Proposed | [AGENTS.md](../AGENTS.md) |
| 5 | Κανάλι επικοινωνίας | _TBD_ | Open | |
| 6 | Daily stand-up | 10–15′, ασύγχρονο αποδεκτό. Ώρα/κανάλι: _TBD_ | Open | [README](../README.md#working-agreements) |
| 7 | Ρόλοι και backups | Primary και backup ανά ρόλο: _TBD_ (βλ. [`roles/`](./roles/README.md)) | Open | |
| 8 | Review rotation | Προτεινόμενος πίνακας στο [`roles/README.md`](./roles/README.md#rotation-reviews-προτεινόμενο) | Proposed | |
| 9 | Definition of Done | 8 κριτήρια στο [`PROJECT_CHECKLIST.md`](./PROJECT_CHECKLIST.md#6-definition-of-done) | Proposed | [README](../README.md#definition-of-done) |
| 10 | Code conventions | Python με type hints, Pydantic, μικρά nodes, χωρίς hardcoded credentials, `.env.example` ενημερωμένο. | Proposed | [AGENTS.md](../AGENTS.md) |
| 11 | Contracts | State (`AgentState`), Pydantic models (`ExtractedFields`, `PolicyResult`, `GraphResult`, `ActionProposal`), 5 actions (`ActionType`), status (`pending`, `approved`, `executed`, `rejected`), tool signatures (`retrieve_policy`, `check_graph`), κανόνας `thread_id` ↔ Chainlit session. | Decided | [ARCHITECTURE_CONTRACTS.md](./ARCHITECTURE_CONTRACTS.md), [`src/agent/schemas.py`](../src/agent/schemas.py), Issue #2 |
| 12 | Pair/mob sessions | Μία στη μέση κάθε εβδομάδας. Ημέρα/ώρα: _TBD_ | Open | |
| 13 | Dependencies & Pinned Versions Policy | Αυστηρό pinning με `==` στο `requirements.txt` και immutable tags στα Docker base images (`python:3.11-slim`, `pgvector/pgvector:pg16`, `neo4j:5.26.0`). Καμία χρήση `:latest` ή `>=`. Αναφορά στο PR και commit scope `deps`. | Decided | [PINNED_VERSIONS.md](./PINNED_VERSIONS.md), Issue #2 |
| 14 | Secrets | Κανένα credential στο repo, `.env` εκτός version control. | Proposed | [AGENTS.md](../AGENTS.md) |
| 15 | Repo Structure & Module Boundaries | Δομή: `src/` (`src/agent/` [Workflow], `src/ui/` [Interface], `src/db/` [Platform], `src/core/` [Platform]), `docker/` (`docker/postgres/init.sql` [Platform]), `scripts/` (`ingest_policies.py`, `seed_neo4j.py` [Knowledge]), `data/` (`policies/`, `eval_dataset.json`, `graph_seed.json` [Knowledge/Quality]), `tests/` & `evals/` [Quality], `docs/` [All/Quality]. Σαφή όρια χωρίς τροποποίηση κοινών αρχείων. | Decided | [COLLABORATION_GUIDE.md](./COLLABORATION_GUIDE.md), [roles/README.md](./roles/README.md), Issue #2 |
| 16 | Docker Base Images & Runtime Pinning | `python:3.11-slim` (app service), `pgvector/pgvector:pg16` (Postgres + pgvector), `neo4j:5.26.0` (Neo4j). Όλα τα services εκκινούν σε <10′ σε καθαρό clone. | Decided | [PINNED_VERSIONS.md](./PINNED_VERSIONS.md), Issue #2 |

## Log αποφάσεων

Μορφή: `Ημερομηνία | Ρόλος | Τι αποφασίστηκε / άλλαξε | Γιατί | Πηγή`

| Ημερομηνία | Ρόλος | Απόφαση / Αλλαγή | Γιατί | Πηγή |
|---|---|---|---|---|
| 2026-11-11 | Quality | Δημιουργία role map, project checklist και αυτού του log | Να παρακολουθούμε την πρόοδο και να έχουμε υλικό για το `CONTRIBUTING.md` | _PR TBD_ |
| 2026-11-16 | Platform | Day 1 Kick-off: Συμφωνία αρχιτεκτονικών συμβολαίων (State, Pydantic models, 5 actions, tool signatures, κανόνας `thread_id` ↔ session), επίσημη δομή repository (`src/`, `docker/`, `scripts/`, `data/`, `tests/`, `evals/`, `docs/`) με σαφή module boundaries, και πολιτική pinned versions για Docker images και Python dependencies (`requirements.txt`). | Διασφάλιση κοινής βάσης, ανεξάρτητη παράλληλη ανάπτυξη με mocks χωρίς merge conflicts, και εγγύηση εκκίνησης stack σε <10′ σε όλα τα λειτουργικά συστήματα (Windows/Linux/macOS). | Issue #2, [ARCHITECTURE_CONTRACTS.md](./ARCHITECTURE_CONTRACTS.md), [PINNED_VERSIONS.md](./PINNED_VERSIONS.md), [COLLABORATION_GUIDE.md](./COLLABORATION_GUIDE.md) |
| 2026-11-17 | Platform | PostgreSQL Schema Init: Ενεργοποίηση `pgvector` extension, πίνακας `tickets` για state-changing ticketing, πίνακας `audit_log` για idempotency tracking και audit trail, πίνακας `policy_chunks` με HNSW index (`embedding vector(1536)`) για το Knowledge retrieval, και επίσημοι πίνακες LangGraph `PostgresSaver` (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) για state persistence και seamless resume μετά από container restart. | Υλοποίηση Issue #5, αποτροπή duplicate executions (idempotency guard), και πλήρης ετοιμότητα βάσης για Workflow και Knowledge roles. | Issue #5, [`docker/postgres/init.sql`](../docker/postgres/init.sql) |

## Team Sign-off (PostgreSQL Database Schema Init – Issue #5)

| Ρόλος | Εκπρόσωπος | Πεδίο Συμφωνίας | Status | Ημερομηνία |
|---|---|---|---|---|
| **Platform** | @vaggelismpomponis (Primary) | `init.sql` script, `vector` extension, HNSW indexing, DB container mounts | **Signed-off** | 2026-11-17 |
| **Workflow** | All members | LangGraph checkpoint schema (`PostgresSaver`), `audit_log` idempotency fields | **Signed-off** | 2026-11-17 |
| **Knowledge** | @stef-fot | `policy_chunks` table, `embedding vector(1536)`, `effective_date` index | **Signed-off** | 2026-11-17 |

## Team Sign-off (Day 1 Contracts & Platform Alignment)

| Ρόλος | Εκπρόσωπος | Πεδίο Συμφωνίας | Status | Ημερομηνία |
|---|---|---|---|---|
| **Platform** | @vaggelismpomponis (Primary) | Pinned versions policy (Docker & Python), Repo Structure, Compose readiness | **Signed-off** | 2026-11-16 |
| **Workflow** | All members | `AgentState`, Pydantic models, 5 action types, `thread_id` session mapping | **Signed-off** | 2026-11-16 |
| **Interface** | @AlexZarkalis | Interrupt payload contracts, Approval cards, UI progress steps | **Signed-off** | 2026-11-16 |
| **Knowledge** | @stef-fot | `PolicyResult` & `GraphResult` tool signatures, `effective_date` precedence | **Signed-off** | 2026-11-16 |
| **Quality** | @VickyMil-ai | Evaluator contracts, 10 test scenarios alignment, CONTRIBUTING.md consistency | **Signed-off** | 2026-11-16 |

## Log προόδου και προβλημάτων (προαιρετικό)

Σύντομες σημειώσεις που βοηθούν στο `CONTRIBUTING.md` ή στο retrospective (π.χ. «το clean-clone test απέτυχε λόγω X»).

| Ημερομηνία | Ρόλος | Σημείωση | Επηρεάζει CONTRIBUTING; |
|---|---|---|---|
| | | | |
