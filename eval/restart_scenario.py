"""Restart test scenario (#53): an approved action survives an app restart and never runs twice.

Each phase runs as its own process inside the app container, with `docker compose restart app`
between phases (see docs/RESTART_TEST_SCENARIO.md):

    docker compose exec -T app python -m eval.restart_scenario start
    docker compose restart app
    docker compose exec -T app python -m eval.restart_scenario approve <thread_id>
    docker compose restart app
    docker compose exec -T app python -m eval.restart_scenario verify <thread_id>

Executions are counted from the checkpoint history in Postgres (every time execute_action moved
the proposal from "approved" to "executed"), because that history survives restarts. Each phase
prints PASS or FAIL lines and exits with 0 only when all its checks pass.
"""

import argparse
import sys
import uuid
from typing import Any

from src.agent.graph import config_for, decide, get_production_graph, pending, start
from src.agent.models import ActionStatus

SENDER = "maria.papadopoulou@nimbus.com"
REQUEST = (
    "My ERP System password is locked out, please reset it. "
    "I work from the Athens office on my MacBook Pro."
)


def _status(value: Any) -> str | None:
    """Proposal status from a state value (an ActionProposal or its dict form)."""
    if value is None:
        return None
    status = value.get("status") if isinstance(value, dict) else getattr(value, "status", None)
    return getattr(status, "value", status)


def count_executions(graph: Any, config: dict) -> int:
    """Times execute_action moved the proposal from approved to executed, from checkpoint history."""
    history = list(graph.get_state_history(config))  # newest first
    count = 0
    for snapshot, parent in zip(history, history[1:]):
        # Only the node name is read from the metadata: src/db/checkpointer.py stores the written
        # values there as text, so the statuses come from the saved state of each step.
        writes = snapshot.metadata.get("writes") if snapshot.metadata else None
        if writes is not None and "execute_action" not in writes:
            continue
        before = _status(parent.values.get("action_proposal"))
        after = _status(snapshot.values.get("action_proposal"))
        if before == ActionStatus.APPROVED.value and after == ActionStatus.EXECUTED.value:
            count += 1
    return count


class Checks:
    def __init__(self) -> None:
        self.failed = 0

    def check(self, ok: bool, label: str, detail: Any = "") -> None:
        self.failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail != "" else ""))


def _graph() -> Any:
    graph = get_production_graph()
    saver = type(graph.checkpointer).__name__
    if saver != "PostgresSaver":
        sys.exit(f"FAIL  checkpointer is {saver}, not PostgresSaver: is Postgres reachable?")
    return graph


def phase_start(checks: Checks) -> None:
    graph = _graph()
    thread_id = f"restart-{uuid.uuid4().hex[:12]}"
    config = config_for(thread_id, SENDER)
    result = start(graph, config, REQUEST)
    proposal = result.get("action_proposal")
    print(f"thread_id: {thread_id}")
    print(f"action_id: {getattr(proposal, 'action_id', None)}")
    checks.check(pending(graph, config) == "approval", "graph paused for approval", pending(graph, config))
    checks.check(_status(proposal) == "pending", "proposal is pending", _status(proposal))
    checks.check(count_executions(graph, config) == 0, "nothing executed before approval")


def phase_approve(checks: Checks, thread_id: str) -> None:
    graph = _graph()
    config = config_for(thread_id, SENDER)
    checks.check(pending(graph, config) == "approval", "still paused for approval after restart", pending(graph, config))
    checks.check(count_executions(graph, config) == 0, "nothing executed while paused")
    if pending(graph, config) != "approval":
        return
    result = decide(graph, config, approved=True)
    checks.check(_status(result.get("action_proposal")) == "executed", "approved action executed",
                 _status(result.get("action_proposal")))
    checks.check(count_executions(graph, config) == 1, "executed exactly once", count_executions(graph, config))


def phase_verify(checks: Checks, thread_id: str) -> None:
    graph = _graph()
    config = config_for(thread_id, SENDER)
    values = graph.get_state(config).values
    checks.check(pending(graph, config) is None, "thread finished after restart", pending(graph, config))
    checks.check(_status(values.get("action_proposal")) == "executed", "status still executed after restart",
                 _status(values.get("action_proposal")))
    checks.check(bool(values.get("final_response")), "final response kept after restart")

    # Replays after the restart: resuming the thread, and a repeated approval guarded like the UI
    # handler (src/app.py only applies a decision while the graph waits for approval).
    graph.invoke(None, config)
    if pending(graph, config) == "approval":
        decide(graph, config, approved=True)
    executions = count_executions(graph, config)
    checks.check(executions == 1, "still executed exactly once after replays", executions)
    checks.check(_status(graph.get_state(config).values.get("action_proposal")) == "executed",
                 "status unchanged after replays")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("phase", choices=["start", "approve", "verify"])
    parser.add_argument("thread_id", nargs="?", help="thread id printed by the start phase")
    args = parser.parse_args()
    if args.phase != "start" and not args.thread_id:
        parser.error(f"{args.phase} needs the thread_id printed by the start phase")

    checks = Checks()
    print(f"== phase: {args.phase}")
    if args.phase == "start":
        phase_start(checks)
    elif args.phase == "approve":
        phase_approve(checks, args.thread_id)
    else:
        phase_verify(checks, args.thread_id)
    print("RESULT:", "PASS" if not checks.failed else f"FAIL ({checks.failed} checks)")
    return 0 if not checks.failed else 1


if __name__ == "__main__":
    sys.exit(main())
