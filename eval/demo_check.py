"""Pre-demo check (#54): every demo request still gives the outcome the demo script expects.

Run inside the app container against the seeded databases, shortly before the demo:

    docker compose exec -T app python -m eval.demo_check

The messages are typed exactly as in docs/DEMO_SCRIPT.md. The UI sends no sender email, so each
message names the employee itself. Approval-requiring requests are left waiting for approval:
nothing is executed. Exits with 0 only when every check passes.
"""

import argparse
import sys
import uuid
from dataclasses import dataclass
from typing import Any

from src.agent.graph import build_graph, config_for, get_production_graph, pending, reply, start


@dataclass(frozen=True)
class DemoStep:
    segment: str
    messages: tuple[str, ...]  # first message, then the answers to clarification questions
    action: str
    waits_for: str | None  # what the graph waits for at the end: "approval" or None
    citation: tuple[str, str]  # (doc_id, effective_date)
    outage_id: str | None = None


DEMO_STEPS = [
    DemoStep(
        segment="2 Clarification",
        messages=(
            "My CRM password stopped working, can you reset it?",
            "I'm employee08@nimbus.com, London office, Linux Workstation.",
        ),
        action="reset_credentials",
        waits_for="approval",
        citation=("POL-001", "2026-09-01"),
    ),
    DemoStep(
        segment="3 Policy version",
        messages=(
            "Do we still allow immediate password resets without human approval "
            "under the password reset policy?",
        ),
        action="answer_policy",
        waits_for=None,
        citation=("POL-001", "2026-09-01"),
    ),
    DemoStep(
        segment="4 Outage",
        messages=(
            "I'm employee03@nimbus.com. I can't log in to GitHub Enterprise, please reset my "
            "password. I'm in London on my MacBook Pro.",
        ),
        action="link_outage",
        waits_for="approval",
        citation=("POL-001", "2026-09-01"),
        outage_id="OUT-2026-01",
    ),
    DemoStep(
        segment="5 Approval",
        messages=(
            "I'm maria.papadopoulou@nimbus.com. My ERP System password is locked out, please "
            "reset it. I work from the Athens office on my MacBook Pro.",
        ),
        action="reset_credentials",
        waits_for="approval",
        citation=("POL-001", "2026-09-01"),
    ),
]


def run_step(graph: Any, step: DemoStep) -> list[str]:
    """Problems found for one demo step; empty when it behaves as the script expects."""
    config = config_for(f"demo-{uuid.uuid4().hex[:12]}", None)
    start(graph, config, step.messages[0])
    for answer in step.messages[1:]:
        if pending(graph, config) != "clarification":
            return ["expected a clarification question before the answer"]
        reply(graph, config, answer)

    values = graph.get_state(config).values
    proposal = values.get("action_proposal")
    policy = values.get("policy_result")
    problems = []
    if pending(graph, config) != step.waits_for:
        problems.append(f"waits for {pending(graph, config)}, expected {step.waits_for}")
    action = proposal.action_type.value if proposal else None
    if action != step.action:
        problems.append(f"action {action}, expected {step.action}")
    cited = (policy.doc_id, policy.effective_date) if policy else None
    if cited != step.citation:
        problems.append(f"cites {cited}, expected {step.citation}")
    if step.outage_id and (proposal.parameters.get("outage_id") if proposal else None) != step.outage_id:
        problems.append(f"outage_id {proposal.parameters.get('outage_id')}, expected {step.outage_id}")
    return problems


def run_all(graph: Any) -> int:
    failed = 0
    for step in DEMO_STEPS:
        problems = run_step(graph, step)
        failed += bool(problems)
        print(f"{'PASS' if not problems else 'FAIL'}  {step.segment}" + "".join(f"\n      {p}" for p in problems))
    return failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="in-memory graph, no Postgres needed")
    args = parser.parse_args()

    graph = build_graph() if args.offline else get_production_graph()
    saver = type(graph.checkpointer).__name__
    print(f"checkpointer: {saver}")
    if not args.offline and saver != "PostgresSaver":
        print("FAIL  not using PostgresSaver: is Postgres reachable?")
        return 1
    failed = run_all(graph)
    print("RESULT:", "PASS" if not failed else f"FAIL ({failed} steps)")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
