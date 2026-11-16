"""Evaluators for the HelpDesk Lite evaluation run.

Each evaluator compares a run outcome (what the graph did) with the expected outputs of one
example in ``eval/dataset.json`` and returns ``{"key", "score", "comment"}``, the result
format used by LangSmith evaluators. Score is 1 (pass) or 0 (fail).

The ``RunOutcome`` shape is Quality's proposal for the contracts discussion. Field and action
names will follow the agreed contracts file.
"""

from typing import Any, Literal, NotRequired, TypedDict

STATE_CHANGING_ACTIONS = {"reset_credentials", "open_ticket"}


class Citation(TypedDict):
    doc_id: str
    effective_date: str


class RunOutcome(TypedDict):
    """What the evaluators need to read from a finished graph run."""

    fields: dict[str, str | None]  # extracted employee, application, urgency
    clarification_asked: bool  # the graph interrupted with a clarification question
    action: str | None  # one of the 5 action types, or None
    citations: list[Citation]
    outage_id: str | None
    escalation_team: str | None
    approval_requested: bool  # the graph paused for human approval
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
    """The proposed action, and its outage or escalation target, match the expected ones."""
    problems = []
    action = outcome["action"]
    if action != expected["expected_action"]:
        problems.append(f"action {action!r}, expected {expected['expected_action']!r}")
    if action in expected["forbidden_actions"]:
        problems.append(f"forbidden action {action!r}")
    if expected["outage_id"] is not None and outcome["outage_id"] != expected["outage_id"]:
        problems.append(f"outage {outcome['outage_id']!r}, expected {expected['outage_id']!r}")
    if (
        expected["escalation_team"] is not None
        and outcome["escalation_team"] != expected["escalation_team"]
    ):
        problems.append(
            f"team {outcome['escalation_team']!r}, expected {expected['escalation_team']!r}"
        )
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
    needs_approval = expected["requires_approval"] or outcome["action"] in STATE_CHANGING_ACTIONS
    if needs_approval and not outcome["approval_requested"]:
        problems.append(f"{outcome['action']!r} proposed without requesting approval")
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
