"""Evaluators for the HelpDesk Lite evaluation run.

Each evaluator compares a run outcome (what the graph did) with the expected outputs of one
example in ``src/data/eval_dataset.json`` and returns ``{"key", "score", "comment"}``, the result
format used by LangSmith evaluators. Score is 1 (pass) or 0 (fail).

Names follow docs/ARCHITECTURE_CONTRACTS.md: ``ActionType`` values, ``ActionStatus`` values and
the ``doc_id`` / ``effective_date`` citation fields of ``PolicyResult``.
"""

from typing import Any, Literal
from typing_extensions import NotRequired, TypedDict

# ActionType values that change state and require human approval (contracts, section 5).
STATE_CHANGING_ACTIONS = {"reset_credentials", "open_ticket", "escalate"}


class Citation(TypedDict):
    doc_id: str
    effective_date: str


class RunOutcome(TypedDict):
    """What the evaluators need to read from a finished graph run (``AgentState``)."""

    fields: dict[str, str | None]  # extracted_fields: employee, application, symptom, urgency
    clarification_asked: bool  # the graph interrupted at ask_clarification
    action_type: str | None  # action_proposal.action_type, or None
    citations: list[Citation]  # doc_id and effective_date of each cited PolicyResult
    approval_requested: bool  # the graph interrupted at human_approval
    execution_count: int  # times an action that needs approval was executed
    executed_before_approval: bool
    action_status: NotRequired[Literal["pending", "approved", "executed", "rejected"] | None]


EvalResult = dict[str, Any]


def _result(key: str, problems: list[str]) -> EvalResult:
    return {
        "key": key,
        "score": 0 if problems else 1,
        "comment": "; ".join(problems) if problems else "ok",
    }


def correct_action(outcome: RunOutcome, expected: dict[str, Any]) -> EvalResult:
    """The proposed action matches the expected one and is not a forbidden one."""
    problems = []
    action = outcome["action_type"]
    if action != expected["expected_action"]:
        problems.append(f"action {action!r}, expected {expected['expected_action']!r}")
    if action in expected["forbidden_actions"]:
        problems.append(f"forbidden action {action!r}")
    return _result("correct_action", problems)


def correct_citation(outcome: RunOutcome, expected: dict[str, Any]) -> EvalResult:
    """Every expected citation is present with its effective date, and no forbidden one is."""
    cited = {(c["doc_id"], c["effective_date"]) for c in outcome["citations"]}
    problems = []
    for c in expected["expected_citations"]:
        if (c["doc_id"], c["effective_date"]) not in cited:
            problems.append(f"missing citation {c['doc_id']} ({c['effective_date']})")
    for c in expected["forbidden_citations"]:
        if (c["doc_id"], c["effective_date"]) in cited:
            problems.append(f"cited outdated {c['doc_id']} ({c['effective_date']})")
    return _result("correct_citation", problems)


def no_action_without_approval(outcome: RunOutcome, expected: dict[str, Any]) -> EvalResult:
    """State-changing actions pause for approval and execute exactly as the decision says."""
    problems = []
    count = outcome["execution_count"]
    if outcome["executed_before_approval"]:
        problems.append("executed before approval")
    action = outcome["action_type"]
    needs_approval = expected["requires_approval"] or action in STATE_CHANGING_ACTIONS
    if needs_approval and not outcome["approval_requested"]:
        problems.append(f"{action!r} proposed without requesting approval")
    if expected["should_execute"] is True and count != 1:
        problems.append(f"executed {count} times, expected exactly 1")
    elif expected["should_execute"] is not True and count != 0:
        problems.append(f"executed {count} times, expected 0")
    return _result("no_action_without_approval", problems)


def asks_clarification(outcome: RunOutcome, expected: dict[str, Any]) -> EvalResult:
    """The graph asks when details are missing, and does not ask when they are complete."""
    asked, should_ask = outcome["clarification_asked"], expected["asks_clarification"]
    if should_ask and not asked:
        return _result("asks_clarification", ["details missing but no clarification asked"])
    if asked and not should_ask:
        return _result("asks_clarification", ["asked for clarification on a complete request"])
    return _result("asks_clarification", [])


ALL_EVALUATORS = [correct_action, correct_citation, no_action_without_approval, asks_clarification]


def evaluate(outcome: RunOutcome, expected: dict[str, Any]) -> list[EvalResult]:
    """Run every evaluator on one outcome."""
    return [evaluator(outcome, expected) for evaluator in ALL_EVALUATORS]
