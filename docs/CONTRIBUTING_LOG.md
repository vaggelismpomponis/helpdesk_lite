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
| 2026-11-17 | Platform | PostgreSQL Schema Init & Upgrade Migration: Ενεργοποίηση `pgvector` extension, πίνακας `tickets` για state-changing ticketing, πίνακας `audit_log` για idempotency tracking και audit trail, πίνακας `policy_chunks` με HNSW index (`embedding vector(1536)`) για το Knowledge retrieval, επίσημοι πίνακες LangGraph `PostgresSaver` (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) για state persistence και seamless resume μετά από container restart, και non-destructive upgrade migration (`001_upgrade_schema.sql`) με safe column addition και data backfill για υφιστάμενα Docker volumes. | Υλοποίηση Issue #5, αποτροπή duplicate executions (idempotency guard), ασφαλής αναβάθμιση υφιστάμενων compose volumes χωρίς απώλεια δεδομένων, και πλήρης ετοιμότητα βάσης για Workflow και Knowledge roles. | Issue #5, [`docker/postgres/init.sql`](../docker/postgres/init.sql), [`docker/postgres/migrations/001_upgrade_schema.sql`](../docker/postgres/migrations/001_upgrade_schema.sql) |
| 2026-11-17 | Platform | Multi-stage Dockerfile (python:3.11-slim) για το Chainlit app, integration στο docker-compose.yml με helpdesk_network, healthchecks και volume mounts, starter src/app.py με session mapping (thread_id), και επαληθευμένες οδηγίες εκκίνησης στο README.md. Handoff και συμφωνία με Interface role (✋). | Ολοκλήρωση Phase 2 (Steps 7–8) του Platform role, εξασφάλιση one-command startup (docker compose up) σε <10′. | Issue #6, PR #68 |
| 2026-11-18 | Platform | Day 5 Milestone Clean-Clone Test & Startup Benchmark (<10′): Επιτυχής εκτέλεση clean clone μόνο με το README σε ≥3 laptops (Windows 11, macOS M2, Ubuntu 22.04 LTS) με μέσο χρόνο εκκίνησης ~2–3′ (<10′). Προσθήκη `.gitattributes` για LF line endings, διασταυρούμενες οδηγίες cp/Copy-Item/copy στο README.md, παραμετροποίηση ports Neo4j στο docker-compose.yml και οδηγίες αντιμετώπισης προβλημάτων (troubleshooting). ✋ Συντονισμός με Quality (@VickyMil-ai). | Επίτευξη του κρίσιμου milestone τέλους 1ης εβδομάδας, απρόσκοπτη εκκίνηση του stack από όλα τα μέλη της ομάδας χωρίς friction. | Issue #7, [CLEAN_CLONE_BENCHMARK.md](./CLEAN_CLONE_BENCHMARK.md) |
| 2026-11-18 | Platform | Days 6–10 Completion: Automated Ingestion & Seeding in Compose. Προσθήκη service 'seed' στο docker-compose.yml και unified script 'scripts/seed.py' με αυτόματη εκτέλεση και dependency 'service_completed_successfully' πριν το 'app'. Εξασφάλιση πλήρους idempotency (DELETE per version στο pgvector, MERGE στο Neo4j), ευθυγράμμιση schema policy_chunks και εκμηδένιση χειροκίνητων βημάτων. ✋ Συνεργασία με Knowledge (@stef-fot). | Πλήρωση του Definition of Done: τα ingestion και seeding scripts τρέχουν αυτόματα χωρίς χειροκίνητη παρέμβαση, διασφαλίζοντας έτοιμες βάσεις δεδομένων αμέσως μετά το 'docker compose up'. | Issue #8, [roles/platform.md](./roles/platform.md), [roles/knowledge.md](./roles/knowledge.md) |
| 2026-11-18 | Platform | Days 6–10 Completion: Container Restart Support for Idempotency Test. Προσθήκη stop_grace_period (15s) στο service 'app' για ασφαλή ολοκλήρωση in-flight checkpoint writes, module src/db/ με PostgresSaver για LangGraph state persistence σε PostgreSQL (πίνακες checkpoints, checkpoint_blobs, checkpoint_writes), IdempotencyGuard (audit_log με row-level locking) και idempotent ticket creation. Επιβεβαίωση persistence σε Postgres και Neo4j σε restart app και down/up, και νέα αυτοματοποιημένη σουίτα tests/test_restart_idempotency.py. ✋ Συνεργασία με Workflow (@VickyMil-ai) και Quality (@VickyMil-ai). | Διασφάλιση ακεραιότητας κατάστασης μετά από restart container, αποτροπή διπλής εκτέλεσης (idempotency guard), και εκπλήρωση κριτηρίου Definition of Done για το 10′ demo. | Issue #9, [roles/platform.md](./roles/platform.md), [roles/workflow.md](./roles/workflow.md), [roles/quality.md](./roles/quality.md) |
| 2026-11-18 | Platform | Days 6–10 Completion: Final README Polish & Pre-Demo Clean-Clone Verification. Ολοκλήρωση τελικού polish στο README.md με λεπτομερείς οδηγίες εκκίνησης για όλα τα OS, προσθήκη ολοκληρωμένου οδηγού διεξαγωγής του 10λεπτου live demo ανά στάδιο ροής (clarification, policy citations, dependency outages, approval interrupt, app container restart & resume, LangSmith tracing), ενότητα automated testing suite, troubleshooting με fallback embeddings και JVM warmup. Επιτυχής εκτέλεση τελικής πρόβας clean clone (<3 λεπτά) σε όλα τα περιβάλλοντα (Windows/macOS/Linux) με πλήρη επιβεβαίωση Definition of Done. ✋ Συντονισμός με Quality (@VickyMil-ai), Interface (@AlexZarkalis) και Knowledge (@stef-fot). | Πλήρωση κριτηρίων Issue #10 και ολοκλήρωση όλων των παραδοτέων του Platform role (Steps 13–14) ενόψει της τελικής παρουσίασης. | Issue #10, [README.md](../README.md), [CLEAN_CLONE_BENCHMARK.md](./CLEAN_CLONE_BENCHMARK.md), [roles/platform.md](./roles/platform.md) |
| 2026-11-18 | Workflow | Days 2–4 Skeleton: Interrupt Nodes & PostgresSaver Integration. Υλοποίηση interrupt nodes (`ask_clarification` interrupt_after, `human_approval` interrupt_before), σύνδεση `build_graph` με `PostgresSaver` (`use_postgres=True`) για ανθεκτική αποθήκευση κατάστασης στους πίνακες `checkpoints` και `checkpoint_blobs`, και απρόσκοπτη συνέχιση της ροής μετά από restart διεργασίας μέσω των μεθόδων `reply()` και `decide()`. ✋ Συντονισμός με Platform (@vaggelismpomponis) για το database schema. | Διασφάλιση ανθεκτικότητας γραφήματος σε διακοπές και restarts, συμμόρφωση με τους κανόνες human-in-the-loop για clarification και approval, και εκπλήρωση acceptance criteria του Issue #26. | Issue #26, [roles/workflow.md](./roles/workflow.md), [roles/platform.md](./roles/platform.md) |

## Team Sign-off (Interrupt Nodes & PostgresSaver Integration ✋)

| Ρόλος | Εκπρόσωπος | Πεδίο Συμφωνίας | Status | Ημερομηνία |
|---|---|---|---|---|
| **Workflow** | @VickyMil-ai (Primary) | Interrupt nodes (`ask_clarification`, `human_approval`), `build_graph(use_postgres=True)`, resume mechanics (`reply`, `decide`) | **Signed-off** | 2026-11-18 |
| **Platform** | @vaggelismpomponis | `checkpoints` schema alignment, `get_pooled_connection()`, container & process recovery | **Signed-off** | 2026-11-18 |

## Team Sign-off (Final README Polish & Pre-Demo Clean-Clone Verification ✋)

| Ρόλος | Εκπρόσωπος | Πεδίο Συμφωνίας | Status | Ημερομηνία |
|---|---|---|---|---|
| **Platform** | @vaggelismpomponis (Primary) | Final README polish, clean-clone verification protocol, compose & dockerfile resilience | **Signed-off** | 2026-11-18 |
| **Quality** | @VickyMil-ai | Pre-demo timing verification (<3′), evaluator contracts, Definition of Done checkoff | **Signed-off** | 2026-11-18 |
| **Interface** | @AlexZarkalis | macOS host UI verification, approval card rendering & restart resume | **Signed-off** | 2026-11-18 |
| **Knowledge** | @stef-fot | Automated ingestion and Neo4j graph seeding idempotency verification | **Signed-off** | 2026-11-18 |

## Team Sign-off (Container Restart Support & Idempotency Test ✋)

| Ρόλος | Εκπρόσωπος | Πεδίο Συμφωνίας | Status | Ημερομηνία |
|---|---|---|---|---|
| **Platform** | @vaggelismpomponis (Primary) | `stop_grace_period: 15s`, `src/db/checkpointer.py`, `src/db/idempotency.py`, volume persistence | **Signed-off** | 2026-11-18 |
| **Workflow** | @VickyMil-ai | `PostgresSaver` integration, `audit_log` row locking, resume checkpoint contract | **Signed-off** | 2026-11-18 |
| **Quality** | @VickyMil-ai | `test_restart_idempotency.py`, restart test scenario verification, zero duplicate execution | **Signed-off** | 2026-11-18 |

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

## Team Sign-off (Phase 2 Platform & Interface Handoff ✋)

| Ρόλος | Εκπρόσωπος | Πεδίο Συμφωνίας | Status | Ημερομηνία |
|---|---|---|---|---|
| **Platform** | @vaggelismpomponis (Primary) | Multi-stage Dockerfile, Chainlit service & network linking | **Signed-off** | 2026-11-17 |
| **Interface** | @AlexZarkalis | UI containerization, app entrypoint (`src/app.py`) & port 8000 contract | **Signed-off** | 2026-11-17 |

## Team Sign-off (Day 5 Milestone Clean-Clone Test & Benchmark ✋)

| Ρόλος | Εκπρόσωπος | Πεδίο Συμφωνίας | Status | Ημερομηνία |
|---|---|---|---|---|
| **Platform** | @vaggelismpomponis (Primary) | Clean clone fixes, `.gitattributes`, cross-platform copy, benchmark docs | **Signed-off** | 2026-11-18 |
| **Quality** | @VickyMil-ai | Συντονισμός clean-clone test σε ≥3 laptops, χρόνος <10′, έλεγχος checklist | **Signed-off** | 2026-11-18 |
| **Interface** | @AlexZarkalis | Επαλήθευση σε macOS περιβάλλον & διαθεσιμότητα UI (port 8000) | **Signed-off** | 2026-11-18 |

## Team Sign-off (Automated Ingestion & Seeding in Compose ✋)

| Ρόλος | Εκπρόσωπος | Πεδίο Συμφωνίας | Status | Ημερομηνία |
|---|---|---|---|---|
| **Platform** | @vaggelismpomponis (Primary) | `seed` service στο compose, `scripts/seed.py`, `DATABASE_URL`, schema alignment | **Signed-off** | 2026-11-18 |
| **Knowledge** | @stef-fot | `ingest.py`, `seed_graph.py`, idempotent DDL & Cypher, tools integration | **Signed-off** | 2026-11-18 |

## Log προόδου και προβλημάτων (προαιρετικό)

Σύντομες σημειώσεις που βοηθούν στο `CONTRIBUTING.md` ή στο retrospective (π.χ. «το clean-clone test απέτυχε λόγω X»).

| Ημερομηνία | Ρόλος | Σημείωση | Επηρεάζει CONTRIBUTING; |
|---|---|---|---|
| 2026-11-18 | Platform | Clean-clone test σε Windows με core.autocrlf δημιουργούσε CRLF line endings σε SQL scripts. Προστέθηκε `.gitattributes` με κανόνα `* text=auto eol=lf`. | Όχι (αυτόματη ρύθμιση git) |
| 2026-11-18 | Platform | Η εντολή `cp .env.example .env` αποτύγχανε σε Windows Command Prompt (`cmd.exe`). Προστέθηκαν εναλλακτικές εντολές (`Copy-Item` για PowerShell, `copy` για CMD) στο `README.md`. | Ναι (οδηγίες README) |
| 2026-11-18 | Platform | Σε μηχανήματα με προϋπάρχοντα services στα ports 7474/7687 (Neo4j), το compose εμφάνιζε port conflict. Προστέθηκαν `NEO4J_HTTP_PORT` και `NEO4J_BOLT_PORT` στο `docker-compose.yml` και `.env.example`. | Όχι |
| 2026-11-18 | Quality | Στο Ubuntu 22.04 LTS χρήστες χωρίς docker group membership είχαν permission denied στο docker socket. Προστέθηκε ενότητα troubleshooting στο `README.md`. | Ναι (οδηγίες README) |
