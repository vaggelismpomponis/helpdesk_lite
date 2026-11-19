# Restart Test Scenario

**Issue:** #53 · **Owner:** Quality · **Collaboration:** Workflow, Interface ✋

## Goal

An action that needs approval must survive an application restart at any point, and must never be
executed twice. The test restarts the `app` container twice:

1. **While the action waits for approval**: after the restart it must still wait, with nothing executed.
2. **After the action was approved and executed**: after the restart the thread must be finished, the action
   still `executed`, and replaying the thread or the approval must not execute it again.

## What counts as an execution

The test counts executions from the checkpoint history in Postgres, which survives restarts: one execution
is one `execute_action` step that moved the proposal from `approved` to `executed`. Since #88 the action is
also recorded in `audit_log` (one row per `action_id`), which is checked after the run.

## Preconditions

- Stack running and healthy: `docker compose up -d --wait`, then `docker compose ps` shows `postgres`,
  `neo4j` and `app` as healthy.
- The graph uses `PostgresSaver`. The script stops with `FAIL` if it falls back to the in-memory saver.

## Procedure A: automated, inside the app container

Each phase runs as a separate process in the container. The restarts happen in between.

```bash
# 1. Request that needs approval (credential reset on ERP System, no outage). Note the thread_id.
docker compose exec -T app python -m eval.restart_scenario start

# 2. Restart while the action waits for approval
docker compose restart app

# 3. Check it is still waiting, then approve (executes the action)
docker compose exec -T app python -m eval.restart_scenario approve <thread_id>

# 4. Restart after execution
docker compose restart app

# 5. Check the finished state, replay the thread and the approval, count executions
docker compose exec -T app python -m eval.restart_scenario verify <thread_id>
```

Each phase prints one `PASS`/`FAIL` line per check and ends with `RESULT: PASS` or `RESULT: FAIL`.

Then check the audit record (use the `action_id` printed by `start`). It should return exactly one row, with
status `executed`:

```bash
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT action_id, status, executed_at FROM audit_log WHERE action_id = '"'"'<action_id>'"'"'"'
```

### Expected results

| Phase | Check | Expected |
|---|---|---|
| start | graph paused for approval | `approval` |
| start | proposal status | `pending` |
| start | executions | 0 |
| approve (after restart 1) | still paused for approval | `approval` |
| approve | executions while paused | 0 |
| approve | status after approving | `executed` |
| approve | executions | 1 |
| verify (after restart 2) | thread finished | nothing pending |
| verify | status and final response | `executed`, response kept |
| verify | executions after replays | 1 |
| verify | status after replays | `executed` |

The replays in `verify` are: resuming the finished thread (`graph.invoke(None, config)`), and repeating the
approval guarded the same way as the UI handler in `src/app.py`, which only applies a decision while the
graph waits for approval.

## Procedure B: manual, through the UI

Same scenario from the user's side. **Blocked until the approval buttons work**: `cl.Action(payload=...)` in
`src/app.py` is the Chainlit 2.x API and fails on the pinned `chainlit==1.3.2`.

1. Open `http://localhost:8000` and send:
   `My ERP System password is locked out, please reset it. I work from the Athens office on my MacBook Pro.`
2. The approval card appears. Do not click. Run `docker compose restart app` and reload the page.
3. Expected: the conversation is restored with the approval card still pending.
4. Click **Approve**. Expected: `Action: reset_credentials [executed]`.
5. Run `docker compose restart app` and reload the page. Expected: the conversation shows the executed action.
6. Click the old **Approve** button again, if still visible. Expected: "This action has already been processed."
   and no second execution.

## Results

### 2026-11-19, Procedure A (macOS, Docker Desktop, `develop` at `f277ced`, with #88)

| Phase | Result | Details |
|---|---|---|
| start | PASS | thread `restart-ceee73e66980`, action `93de148a-31bd-4b10-8f63-e281da4c7d77`, paused for approval |
| restart 1 | done | app healthy again after 6 s |
| approve | PASS | still paused after the restart, 0 executions while paused, executed exactly once |
| restart 2 | done | app healthy again after 6 s |
| verify | PASS | finished, `executed`, response kept, still 1 execution after both replays |
| audit_log | PASS | exactly one row for the action, status `executed`, `executed_at` set |

**Zero duplicate executions across two app restarts**, in both the checkpoint history and `audit_log`.

An earlier run the same day, before #88 (`develop` at `db50749`), also passed all phases, but
`audit_log` and `tickets` stayed empty: executions were only kept in memory.

### Procedure B

Not run: blocked by the approval-button error described above.

## Findings

1. **Resolved by #88: executions are recorded in the database.** Before #88, `execute_action` kept executed
   `action_id`s only in memory and `audit_log` stayed empty. Since #88 each action has one `audit_log` row,
   and execution goes through the idempotent helpers in `src/db/idempotency.py`. Confirmed in the run above.
2. **Resolved by #88: the README is now accurate.** The section "Container Restart & Idempotency Testing"
   says actions are tracked in `audit_log` and `tickets`, which was not true before #88.
3. **`decide()` has no guard** (still present after #88). Calling `decide(graph, config, approved=True)` on a finished thread changes the
   saved status from `executed` back to `approved` (nothing executes, but the record is wrong). The UI is
   protected because `src/app.py` checks `pending(...) == "approval"` first; other callers are not.
   → Workflow: return early in `decide()` when the graph is not waiting for approval.
4. **Checkpoint history stores writes as text.** `src/db/checkpointer.py` saves the values in
   `metadata["writes"]` as their printed form, not as objects. The state itself is saved correctly. This only
   matters to code that reads the history, like this test, which reads statuses from the saved state instead.
5. **Procedure B is blocked** by the approval-button error on Chainlit 1.3.2. → Interface.

## Sign-off

| Role | Who | Status | Date |
|---|---|---|---|
| Quality | @VickyMil-ai | Procedure A executed | 2026-11-19 |
| Workflow | | | |
| Interface | | Procedure B pending | |
