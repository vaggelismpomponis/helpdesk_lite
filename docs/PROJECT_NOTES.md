# HelpDesk Lite – Σημειώσεις Warm-up Project (Agentic AI Bootcamp – Code.Hub / PwC)

## Περιεχόμενα
1. [Περίληψη του project](#1-περίληψη-του-project)
2. [Σχεδιασμός για ομάδα 5 ατόμων](#2-σχεδιασμός-για-ομάδα-5-ατόμων)
3. [Codeberg: Πώς κάνω merge ένα PR](#3-codeberg-πώς-κάνω-merge-ένα-pr)

---

## 1. Περίληψη του project

### Στόχος
Ένας agentic AI βοηθός για μηχανικούς IT support. Μειώνει τον χρόνο μέχρι την πρώτη σωστή απάντηση σε ένα αίτημα. Ένας άνθρωπος παραμένει υπεύθυνος για κάθε ενέργεια που αλλάζει λογαριασμούς ή συστήματα. Το project είναι warm-up. Η ομάδα στήνει κοινό stack και αποδεικνύει ότι τα βασικά components δουλεύουν πριν το τελικό project.

### Τι πρέπει να κάνει ο βοηθός
1. **Εξαγωγή πεδίων** από το αίτημα: employee, application, symptom, urgency.
2. **Διευκρινιστικές ερωτήσεις** όταν λείπουν βασικά στοιχεία. Δεν μαντεύει.
3. **Αναζήτηση πολιτικών** σε document store, με παράθεση πηγής και effective date.
4. **Έλεγχος service graph** για εξαρτήσεις και ενεργά outages.
5. **Πρόταση μίας από 5 ενέργειες:** απάντηση από policy, σύνδεση με outage, reset credentials, άνοιγμα ticket ή escalation σε μηχανικό.
6. **Human-in-the-loop:** Σταματά και περιμένει έγκριση πριν από ενέργεια που αλλάζει λογαριασμό ή δημιουργεί ticket.
7. **Persistence:** Αν η εφαρμογή κάνει restart κατά την αναμονή έγκρισης, η συνομιλία συνεχίζεται από το ίδιο σημείο.

### Τεχνολογίες
| Τεχνολογία | Χρήση |
|---|---|
| LangGraph | workflow, state, interrupts |
| Chainlit | UI: chat, progress, κουμπιά έγκρισης |
| LangChain Core | prompts, models, tools, Pydantic |
| Docker Compose | orchestration των υπηρεσιών |
| PostgreSQL + pgvector | tickets, LangGraph checkpoints, semantic search των policies |
| Neo4j | employees, teams, applications, services, outages |
| LangSmith | tracing και evaluation |

### Παραδοτέα
- Repo με `docker-compose.yml`, `.env.example` και `README`. Όλα τα services πρέπει να ξεκινούν σε **<10 λεπτά**.
- Λειτουργική εφαρμογή Chainlit.
- Scripts για policy ingestion και graph seeding.
- Project στο LangSmith με traces και evaluation run σε **10 test requests**.
- `CONTRIBUTING.md` με τη συμφωνία της ομάδας.
- **Live demo 10 λεπτών**, με επίδειξη του «resume after restart».

### Περιορισμοί
- **Εκτός scope:** multi-agent patterns, MCP, επιπλέον vector stores, model training, adversarial testing.
- Η business logic μένει σκόπιμα απλή.
- Καμία ενέργεια χωρίς ρητή ανθρώπινη έγκριση.
- Ένα restart δεν πρέπει να εκτελέσει εγκεκριμένη ενέργεια **δύο φορές** (idempotency).
- Σε παλιές εκδόσεις policy υπερισχύει το έγγραφο με την πιο πρόσφατη effective date.
- Πρέπει να λαμβάνονται υπόψη οι εξαρτήσεις υπηρεσιών.

### Κριτήρια αξιολόγησης
- Σωστή παράθεση εγγράφων και effective dates.
- Κάθε ενέργεια είναι ιχνηλάσιμη στο LangSmith.
- Ολοκληρώνονται τα 10 evaluation requests με τις αναμενόμενες ενέργειες.
- **Κάθε μέλος μπορεί να εξηγήσει ολόκληρη τη ροή** στο demo.

### Χρονοδιάγραμμα (2 εβδομάδες)
| Στιγμή | Ορόσημο |
|---|---|
| Εβδ. 1, 1η συνεδρία | Kick-off, ρόλοι, repo, team agreement |
| Τέλος εβδ. 1 | Πλήρες stack τρέχει σε όλα τα laptops |
| Μέσα εβδ. 2 | End-to-end ροή με approval και resume |
| Τέλος εβδ. 2 | Evaluation run και τελικό demo |

### Κανόνες ομάδας
- Προτεινόμενοι ρόλοι: Platform, Interface, Workflow, Knowledge, Quality.
- Κάθε μέλος κάνει commit κώδικα.
- Πριν ξεκινήσει ο κώδικας, η ομάδα συμφωνεί σε: branch strategy, κανόνα PR (≥1 reviewer), κανάλι επικοινωνίας και definition of done. Όλα καταγράφονται στο `CONTRIBUTING.md`.

---

## 2. Σχεδιασμός για ομάδα 5 ατόμων

### 2.1 Βασικές αρχές
1. **Όχι silos.** Κάθε ρόλος έχει κύριο υπεύθυνο αλλά όχι αποκλειστική γνώση. Χρειάζονται pair sessions και rotation στα reviews.
2. **Walking skeleton πρώτα.** Στήστε νωρίς μια end-to-end ροή με mocks και αντικαταστήστε τα σταδιακά.
3. **Contracts πριν τον κώδικα:** State schema, Pydantic models, tool signatures.
4. **Απλή λογική.** Η αξία του project είναι στο stack και στα patterns (interrupt, checkpoint, tracing).

### 2.2 Ρόλοι
| Ρόλος | Κύρια ευθύνη | Παραδοτέα |
|---|---|---|
| **Platform** | Docker Compose, Postgres+pgvector, Neo4j, `.env.example`, README | Stack που ξεκινά με μία εντολή σε <10′ |
| **Interface** | Chainlit UI: chat, progress steps, κουμπιά Approve/Reject, resume | Λειτουργικό UI |
| **Workflow** | LangGraph: nodes, edges, state, interrupt, PostgresSaver, idempotency | Γράφος με approval και resume |
| **Knowledge** | Policy ingestion (chunking, embeddings, metadata με effective date), Neo4j seeding, retrieval και graph tools | Scripts και tools |
| **Quality** | LangSmith tracing, dataset των 10 requests, evaluators, CONTRIBUTING.md, test scenarios, demo | Evaluation run και demo script |

Ο Quality ξεκινά νωρίς με test cases και δεδομένα, και δεν περιμένει το τέλος.

### 2.3 Αρχιτεκτονική ροής (LangGraph)

```
[Είσοδος αιτήματος]
      ↓
[extract_fields] → (Pydantic: employee, app, symptom, urgency)
      ↓
[έλλειψη πεδίων;] —ναι→ [ask_clarification] → (interrupt) → πίσω στο extract
      ↓ όχι
[retrieve_policy] (pgvector + κανόνας πιο πρόσφατης effective date)
      ↓
[check_graph] (Neo4j: εξαρτήσεις, ενεργά outages)
      ↓
[decide_action] → μία από 5 ενέργειες
      ↓
[ενέργεια αλλάζει κατάσταση;] —ναι→ [human_approval] (interrupt) → approve/reject
      ↓                                         ↓
[answer / link outage]                  [execute_action] (idempotent)
      ↓                                         ↓
                    [τελική απάντηση με citations]
```

**Σημεία προσοχής**
- **Interrupt + checkpointer:** Το `thread_id` αντιστοιχεί σταθερά στη συνεδρία Chainlit, ώστε μετά το restart να βρίσκεται το σωστό thread.
- **Idempotency:** Αποθηκεύστε `action_id` ή status (`pending → approved → executed`) στη βάση και ελέγξτε το πριν την εκτέλεση.
- **Παλιές εκδόσεις policy:** Κρατήστε `effective_date` και `doc_id` στα metadata. Στο retrieval κρατήστε την πιο πρόσφατη έκδοση.
- **Εξαρτήσεις υπηρεσιών:** Αν το app εξαρτάται από service με ενεργό outage, η σωστή ενέργεια είναι *link to outage* και όχι reset password.

### 2.4 Χρονοπλάνο

**Εβδομάδα 1 – Θεμέλια**
- *Ημέρα 1 (kick-off):*
  - Ρόλοι και backup ρόλοι.
  - Repo και `CONTRIBUTING.md`: branch strategy (π.χ. `main` προστατευμένο, `feature/*`), κανόνας PR (1 reviewer, όχι self-merge), κανάλι επικοινωνίας, Definition of Done.
  - Συμφωνία στα contracts: State, Pydantic models, τα 5 action types.
  - Board με tasks.
- *Ημέρες 2–4:*
  - Platform: Compose με Postgres+pgvector και Neo4j, μετά το app container.
  - Workflow: σκελετός γράφου με mock nodes.
  - Interface: βασικό Chainlit.
  - Knowledge: dataset (policies με παλιές και νέες εκδόσεις, graph model) και πρώτα scripts.
  - Quality: LangSmith και πρώτο σχέδιο των 10 requests.
- *Ημέρα 5 (milestone):* Το stack τρέχει σε **όλα** τα laptops. Κάντε clean-clone test με μόνο το README.

**Εβδομάδα 2 – Ολοκλήρωση**
- *Ημέρες 6–8:*
  - Αντικατάσταση mocks με πραγματικά tools.
  - Interrupt, approval buttons, resume.
  - Δοκιμή restart χωρίς διπλή εκτέλεση.
  - **Milestone:** End-to-end με approval και resume.
- *Ημέρες 9–10:*
  - Evaluation run στο LangSmith.
  - Διορθώσεις και έλεγχος citations.
  - 2–3 πρόβες του demo.
  - Final polish των README και CONTRIBUTING.

### 2.5 Πρόταση για τα 10 test requests
- 2 απλές ερωτήσεις με απάντηση από policy.
- 1–2 με **παλιά και νέα έκδοση** της ίδιας policy.
- 2 με **ενεργό outage** σε εξαρτώμενο service.
- 2 με **reset credentials** (με approval).
- 1 με **ticket**.
- 1 με **escalation**.
- 1 με **ελλιπή στοιχεία** (διευκρίνιση).

### 2.6 Ρουτίνες συνεργασίας
- Daily stand-up 10–15′, ακόμα και ασύγχρονο.
- Μικρά PRs (<300 γραμμές), review εντός 24 ωρών.
- Rotation στα reviews.
- Pair/mob session στη μέση κάθε εβδομάδας.
- Εβδομαδιαίο integration time.
- Ουσιαστικά commits από όλους.

### 2.7 Ρίσκα
| Ρίσκο | Αντιμετώπιση |
|---|---|
| «Δουλεύει στο laptop μου» | Docker, pinned versions, clean-clone test |
| Duplicate execution μετά από restart | Status στη βάση, έλεγχος πριν την εκτέλεση, δοκιμή restart |
| Το LLM μαντεύει πεδία | Optional πεδία στο Pydantic και κανόνας «αν λείπει, ρώτα» |
| Λάθος έκδοση policy | Metadata `effective_date`, ταξινόμηση, test case |
| Κάποιος δεν ξέρει τη ροή | Rotation στα reviews και στις πρόβες |
| Scope creep | Τήρηση της λίστας «εκτός scope» |
| Καθυστέρηση στο Platform | Όλοι βοηθούν τις ημέρες 2–3 |
| Μη επαναλήψιμο demo | Script, seed data, πρόβα του restart |

### 2.8 Demo 10 λεπτών
1. (1′) Στόχος και αρχιτεκτονική.
2. (2′) Αίτημα με ελλιπή στοιχεία και διευκρίνιση.
3. (2′) Αίτημα με policy, citation και effective date.
4. (2′) Αίτημα με outage και service dependency.
5. (2′) Ενέργεια με approval, **restart** και resume χωρίς διπλή εκτέλεση.
6. (1′) LangSmith traces και evaluation.

### 2.9 Definition of Done (checklist)
- [ ] `docker compose up` ξεκινά όλα τα services σε <10′ από καθαρό clone.
- [ ] Τα ingestion και seeding scripts τρέχουν χωρίς χειροκίνητα βήματα.
- [ ] Καμία state-changing ενέργεια χωρίς approval.
- [ ] Το resume μετά από restart δουλεύει, χωρίς διπλή εκτέλεση.
- [ ] Citations με πηγή και effective date.
- [ ] Traces στο LangSmith και evaluation σε 10 requests.
- [ ] `CONTRIBUTING.md` συμπληρωμένο και όλοι έχουν commits.
- [ ] Όλοι μπορούν να εξηγήσουν ολόκληρη τη ροή.

---

## 3. Codeberg: Πώς κάνω merge ένα PR

### Η περίπτωσή μας
Το PR #1 («Update README.md to include project overview and usage instructions», `feature/readme-update` → `main`) ήταν σε κατάσταση **Closed**. Το Codeberg (Forgejo) δεν επιτρέπει merge σε κλειστό PR: *"Please reopen this pull request to perform a merge."*

### Βήματα
1. Πάτα **«Reopen»**, δίπλα στο «Comment», κάτω από το πλαίσιο σχολίου.
2. Κάτω στη συνομιλία εμφανίζεται το πλαίσιο merge με το κουμπί **«Create merge commit»**. Το βέλος δίπλα του δίνει επιλογές.
3. Διάλεξε τρόπο merge και πάτα το κουμπί.
4. Προαιρετικά, πάτα **«Delete branch»** για να σβήσεις το `feature/readme-update`.

### Τρόποι merge
| Επιλογή | Τι κάνει |
|---|---|
| Merge commit | Κρατά όλο το ιστορικό και προσθέτει merge commit |
| Rebase and merge | Βάζει τα commits πάνω στο main χωρίς merge commit |
| Squash and merge | Συμπιέζει όλα τα commits σε ένα |
| Fast-forward only | Merge μόνο αν δεν υπάρχει divergence |

> Η επιλογή τρόπου merge καλό είναι να γραφτεί στο `CONTRIBUTING.md`.

### Το μήνυμα «Dependent issue does not exist»
Συνήθως δεν εμποδίζει το merge. Προέρχεται από το σύστημα dependencies. Αν επιμένει μετά το Reopen, δες την ενότητα **Dependencies** στο πλαϊνό μενού και αφαίρεσε ό,τι έχει προστεθεί εκεί.

### Αν δεν εμφανίζεται κουμπί merge
- **Conflicts:** Κάνε τοπικά merge ή rebase του `main` στο branch σου και μετά push.
- **Branch protection:** Αν απαιτείται reviewer, χρειάζεται approval από άλλο μέλος (Settings → Branches).
- **Δικαιώματα:** Χρειάζεται write access στο repo.
- **Checks:** Τυχόν required CI checks πρέπει να περάσουν.

### Μετά το merge (όλα τα μέλη)
```bash
git checkout main
git pull origin main
```

### Καλή πρακτική
Πρόσθεσε reviewer από το **Reviewers** (πάνω δεξιά). Το merge γίνεται μετά το approval. Αν ο κανόνας σας ζητά review, αποφύγετε το merge του δικού σας PR χωρίς έγκριση.