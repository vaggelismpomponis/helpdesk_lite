# Demo Script (10 minutes)

**Issue:** #54 · **Owner:** Quality · **Presenters:** rotate per segment, see [REHEARSAL_LOG.md](./REHEARSAL_LOG.md) (#55)

The demo runs on the seeded stack from `docker compose up`. Every message below was run against it on
2026-11-19 with `eval/demo_check.py` and gave the outcome described.

## Timing

| # | Time | Segment | Shown in |
|---|---|---|---|
| 1 | 0:00–1:00 | Objective & stack | slides / README |
| 2 | 1:00–3:00 | Clarification flow | UI |
| 3 | 3:00–5:00 | Policy citation & version conflict | UI |
| 4 | 5:00–7:00 | Outage detection & link to outage | UI, Neo4j Browser |
| 5 | 7:00–9:00 | Human approval & container restart resume | terminal (see [Known issues](#known-issues)) |
| 6 | 9:00–10:00 | LangSmith tracing & evaluation run | terminal, LangSmith |

## Before the demo (T-30 min)

```bash
docker compose up -d --wait               # postgres, neo4j, app healthy; seed has exited
docker compose ps
docker compose exec -T app python -m eval.demo_check   # must end with RESULT: PASS
```

Open these tabs:

- UI: http://localhost:8000
- Neo4j Browser: http://localhost:7474
- LangSmith, project `helpdesk-lite`

Keep a terminal in the repo root. Copy the messages from this file; don't retype them.

## 1. Objective & stack (1′)

- **Problem:** IT support requests that need policy lookups, outage awareness and safe account changes.
- **Rule:** nothing that changes an account or opens a ticket runs without a human approval, and every
  action runs at most once.
- **Stack:**

  | Component | Used for |
  |---|---|
  | LangGraph | workflow, pause/resume |
  | Chainlit | UI |
  | PostgreSQL + pgvector | policies, checkpoints |
  | Neo4j | applications → services → outages |
  | LangSmith | tracing, evaluation |

- **Flow:** extract fields → (clarify) → retrieve policy → check graph → decide → (approve) → execute.

## 2. Clarification flow (2′)

Send:

```text
My CRM password stopped working, can you reset it?
```

Expected: the agent asks who you are, which office and which device. It does nothing yet.

Answer:

```text
I'm employee08@nimbus.com, London office, Linux Workstation.
```

Expected: the agent proposes `reset_credentials` for **Employee 08** on **CRM** and waits for approval,
citing **POL-001 (effective 2026-09-01)**.

Point out:

- POL-001 v2 requires confirming office and device before acting, so the agent asks for them instead
  of guessing.
- The graph paused at a breakpoint and resumed in the same thread with the answer.
- Leave this approval alone. Segment 5 shows approvals.

## 3. Policy citation & version conflict (2′)

Send:

```text
Do we still allow immediate password resets without human approval under the password reset policy?
```

Expected: `answer_policy`, citing **POL-001 (effective 2026-09-01)**.

Point out the conflict in the seed data. Both versions of POL-001 are indexed:

| File | Effective | Says |
|---|---|---|
| `POL-001_password_reset_v1.md` | 2024-03-15 (superseded) | reset immediately on request, without checking outages |
| `POL-001_password_reset_v2.md` | 2026-09-01 | check outages first, confirm office and device, every reset needs human approval |

Retrieval returns only the latest effective version of each policy. That's why the answer cites v2's
date and never v1.

## 4. Outage detection & link to outage (2′)

Send:

```text
I'm employee03@nimbus.com. I can't log in to GitHub Enterprise, please reset my password. I'm in London on my MacBook Pro.
```

Expected:

- `link_outage` to **OUT-2026-01**, with no approval needed.
- The response says: *"Active outage on dependent service (Identity Provider (SSO)) affecting GitHub
  Enterprise. Credential reset is inhibited; proposing link to outage instead."*

Point out:

- The user asked for a reset, but GitHub Enterprise depends on Identity Provider (SSO), which has an
  open critical outage. POL-001 v2 rule 1 says to link to the outage instead.
- Show it in Neo4j Browser:

  ```cypher
  MATCH p=(:Application {name:'GitHub Enterprise'})-[:DEPENDS_ON]->(:Service)-[:HAS_OUTAGE]->(:Outage {status:'OPEN'})
  RETURN p
  ```

  Expected path: GitHub Enterprise → Identity Provider (SSO) → OUT-2026-01.

## 5. Human approval & container restart resume (2′)

This uses the restart procedure from `docs/RESTART_TEST_SCENARIO.md` (#53), which shows the same thing
from the terminal. The request is:

```text
I'm maria.papadopoulou@nimbus.com. My ERP System password is locked out, please reset it. I work from the Athens office on my MacBook Pro.
```

```bash
docker compose exec -T app python -m eval.restart_scenario start          # paused for approval; note thread_id
docker compose restart app                                                # kill the app while it waits
docker compose exec -T app python -m eval.restart_scenario approve <thread_id>   # still waiting -> approve -> executed once
docker compose restart app
docker compose exec -T app python -m eval.restart_scenario verify <thread_id>    # replays: still executed once
```

Point out:

- The approval state lives in the Postgres checkpointer, not in the app process, so the restart loses
  nothing.
- Every action has an `action_id`. Replaying the thread or repeating the approval doesn't execute it
  again.
- `audit_log` has exactly one row for the action, with status `executed`. The query is in the restart doc.
- ERP System has no outage, so here a reset is the right action. Compare with segment 4.

If the approval buttons work by demo day, do this in the UI instead (Procedure B in the restart doc).
Send the message, restart the app, reload, click **Approve**.

## 6. LangSmith tracing & evaluation run (1′)

- In LangSmith (`helpdesk-lite`), open the trace of the segment 4 request. Show the node sequence,
  the retrieved policy and the graph result.
- Run the evaluation on the 10-request dataset:

  ```bash
  docker compose exec -T app python -m eval.run_eval
  ```

- **Evaluators:**
  - correct action
  - correct citation (latest version, never the superseded one)
  - no action without approval
  - asks for clarification when needed
- Optional, if time allows: `python -m eval.run_eval --langsmith` creates an experiment in LangSmith.

## Seed data

Seeding is automatic: the `seed` service runs `scripts/seed.py` on `docker compose up`. It is idempotent:

- `src/data/policies/`: 20 policy files (POL-001 to POL-019, with two versions of POL-001), embedded
  into pgvector.
- `src/data/graph_seed.json`: 40 employees, 12 applications, 10 services, 2 open outages, loaded into
  Neo4j.

The records the demo depends on:

| Record | Value | Used in |
|---|---|---|
| Employee 08 | `employee08@nimbus.com`, London | 2 |
| Employee 03 | `employee03@nimbus.com`, London, MacBook Pro | 4 |
| Maria Papadopoulou | `maria.papadopoulou@nimbus.com`, Athens, MacBook Pro | 5 |
| CRM | depends on API Gateway, Auth Token Service (no outage) | 2 |
| GitHub Enterprise | depends on Identity Provider (SSO), Cloud Storage | 4 |
| ERP System | depends on PostgreSQL Cluster, API Gateway (no outage) | 5 |
| OUT-2026-01 | Identity Provider (SSO), critical, OPEN | 4 |
| POL-001 v1 / v2 | effective 2024-03-15 (superseded) / 2026-09-01 | 2–5 |

To reseed without losing checkpoints: `docker compose run --rm seed`. Don't run
`docker compose down -v` before the demo: it deletes the database volumes, and the first startup after
it takes several minutes.

Check the seed data with `docker compose exec -T app python -m eval.demo_check`. It runs every demo
message above against the live stack and checks the action, the citation and the outage. Approvals are
left pending, so nothing executes.

## Known issues

These were found on 2026-11-19. Recheck before the demo.

1. **The UI approval buttons fail** on the pinned `chainlit==1.3.2`. `cl.Action(payload=...)` is the
   Chainlit 2.x API, and 1.3.2 requires `value`. In segment 2 the approval card won't render. That's why
   segment 5 is done from the terminal. → Interface.
2. **The live evaluation scores 8/10, not 10/10.** With real policy search, EVAL-06 cites POL-008
   instead of POL-003, and EVAL-09 cites POL-012 instead of POL-004. The demo avoids both requests.
   Show the score as it is, and say that citation retrieval is being tuned. Running `eval.run_eval` from
   the host instead of the container uses the offline fallback (`DATABASE_URL` in `.env` points to the
   `postgres` hostname), so it reports 10/10. → Workflow / Knowledge.
3. **The UI has no logged-in user**, so the agent doesn't know who is writing. Every demo message names
   the employee, or the agent asks for it.
4. **Responses end with a doubled period** ("instead.."). This is cosmetic.

## Fallbacks

| Problem | Do this |
|---|---|
| UI unreachable | `docker compose restart app`. Meanwhile, run `eval.demo_check` in the terminal to show the outcomes |
| Neo4j Browser login fails | show the `active_outages` and `outage_id` in the agent's response instead |
| LangSmith slow or offline | show the local `eval.run_eval` table only |
| Segment running long | skip the Neo4j query in segment 4 and the `--langsmith` run in segment 6 |
