# Project Checklist – HelpDesk Lite

Project-wide πρόοδος. Τα βήματα ανά ρόλο βρίσκονται στο [`roles/`](./roles/README.md). Τικάρουμε ένα item όταν είναι merged στο `develop`.

**Owner ενημέρωσης:** Quality (έλεγχος στο mid-week και πριν το demo).

## 1. Kick-off (Εβδ. 1, Ημ. 1)

- [ ] Ρόλοι και backup ρόλοι ορίστηκαν (`CONTRIBUTING_LOG.md`)
- [ ] Repo, `main`/`develop` προστατευμένα
- [ ] Branch strategy, κανόνας PR, merge method, κανάλι επικοινωνίας συμφωνημένα
- [ ] Definition of Done συμφωνημένο
- [ ] **Contracts**: State schema
- [ ] **Contracts**: Pydantic models (`ExtractedFields`, `PolicyResult`, `GraphResult`)
- [ ] **Contracts**: 5 action types και status (`pending`, `approved`, `executed`)
- [ ] **Contracts**: tool signatures (`retrieve_policy`, `check_graph`)
- [ ] **Contracts**: κανόνας `thread_id` ↔ Chainlit session
- [ ] Board με tasks
- [ ] Draft `CONTRIBUTING.md`

## 2. Walking skeleton (Ημ. 2–4)

- [ ] Docker Compose: Postgres + pgvector, Neo4j
- [ ] `.env.example` και `.env` εκτός version control
- [ ] Graph με mock nodes
- [ ] Βασικό Chainlit UI με mock graph
- [ ] Dataset policies (παλιές/νέες εκδόσεις) και graph model
- [ ] LangSmith project και πρώτο σχέδιο 10 requests

## 3. Milestone: τέλος εβδομάδας 1 (Ημ. 5)

- [ ] Το stack τρέχει σε **όλα** τα laptops (clean-clone test μόνο με README)
- [ ] Χρόνος εκκίνησης <10′
- [ ] End-to-end ροή με mocks μέσα στο compose

## 4. Ολοκλήρωση (Ημ. 6–8)

- [ ] Mocks αντικαταστάθηκαν με πραγματικά tools
- [ ] Interrupt για clarification και approval
- [ ] Approve/Reject στο UI
- [ ] Idempotent `execute_action`
- [ ] Resume μετά από restart
- [ ] Restart test: καμία διπλή εκτέλεση
- [ ] **Milestone: end-to-end με approval και resume (μέσα εβδ. 2)**

## 5. Evaluation και demo (Ημ. 9–10)

- [ ] Evaluation run στο LangSmith, 10/10 με αναμενόμενες ενέργειες
- [ ] Citations ελεγμένα (πηγή, `doc_id`, `effective_date`)
- [ ] Demo script και seed data
- [ ] ≥2 πρόβες με rotation
- [ ] Final polish README και `CONTRIBUTING.md`
- [ ] Τελικό clean-clone test

## 6. Definition of Done

- [ ] `docker compose up` ξεκινά όλα τα services σε <10′ από καθαρό clone
- [ ] Τα ingestion και seeding scripts τρέχουν χωρίς χειροκίνητα βήματα
- [ ] Καμία state-changing ενέργεια χωρίς approval
- [ ] Το resume μετά από restart δουλεύει, χωρίς διπλή εκτέλεση
- [ ] Citations με πηγή και effective date
- [ ] Traces στο LangSmith και evaluation σε 10 requests
- [ ] `CONTRIBUTING.md` συμπληρωμένο και όλοι έχουν commits
- [ ] Όλοι μπορούν να εξηγήσουν ολόκληρη τη ροή

## 7. Πρόοδος ανά ρόλο

Ενημερώνεται χειροκίνητα από τα role checklists.

| Ρόλος | Checklist | Πρόοδος | Owner | Backup |
|---|---|---|---|---|
| Platform | [`platform.md`](./roles/platform.md) | 0/13 | _TBD_ | _TBD_ |
| Interface | [`interface.md`](./roles/interface.md) | 0/14 | _TBD_ | _TBD_ |
| Workflow | [`workflow.md`](./roles/workflow.md) | 0/14 | _TBD_ | _TBD_ |
| Knowledge | [`knowledge.md`](./roles/knowledge.md) | 0/13 | _TBD_ | _TBD_ |
| Quality | [`quality.md`](./roles/quality.md) | 0/16 | _TBD_ | _TBD_ |

## 8. Ρίσκα που παρακολουθούμε

Πλήρης πίνακας στο [README](../README.md#risk-register). Ενημερώστε εδώ μόνο όταν ένα ρίσκο ενεργοποιείται.

| Ημερομηνία | Ρίσκο | Ενέργεια | Owner |
|---|---|---|---|
| | | | |
