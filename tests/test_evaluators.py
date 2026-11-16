"""Tests for the dataset loader and the evaluators, using fake run outcomes."""

import pytest

from eval.dataset import load_examples
from eval.evaluators import (
    RunOutcome,
    asks_clarification,
    correct_action,
    correct_citation,
    evaluate,
    no_action_without_approval,
)

EXAMPLES = {example["metadata"]["id"]: example for example in load_examples()}
EXPECTED = {example_id: example["outputs"] for example_id, example in EXAMPLES.items()}


def perfect_outcome(expected: dict) -> RunOutcome:
    """The outcome a fully correct graph would produce for an example."""
    return {
        "fields": {},
        "clarification_asked": expected["asks_clarification"],
        "action": expected["expected_action"],
        "citations": [dict(c) for c in expected["expected_citations"]],
        "outage_id": expected["outage_id"],
        "escalation_team": expected["escalation_team"],
        "approval_requested": expected["requires_approval"],
        "execution_count": 1 if expected["should_execute"] else 0,
        "executed_before_approval": False,
    }


# --- Dataset loader ---


def test_loads_all_ten_examples():
    assert len(EXAMPLES) == 10


def test_older_policy_version_is_forbidden():
    forbidden = EXPECTED["EVAL-04"]["forbidden_citations"]
    assert {"doc_id": "POL-001", "effective_date": "2024-03-15"} in forbidden


def test_reset_is_forbidden_when_outage_expected():
    assert "reset_credentials" in EXPECTED["EVAL-01"]["forbidden_actions"]


def test_approval_defaults_to_approve_and_execute():
    assert EXAMPLES["EVAL-07"]["inputs"]["approval_decision"] == "approve"
    assert EXPECTED["EVAL-07"]["should_execute"] is True
    assert EXPECTED["EVAL-02"]["should_execute"] is False


# --- Evaluators ---


@pytest.mark.parametrize("example_id", sorted(EXPECTED))
def test_perfect_outcome_passes_every_evaluator(example_id):
    expected = EXPECTED[example_id]
    results = evaluate(perfect_outcome(expected), expected)
    assert all(r["score"] == 1 for r in results), results


def test_wrong_action_fails():
    expected = EXPECTED["EVAL-02"]
    outcome = perfect_outcome(expected) | {"action": "open_ticket"}
    assert correct_action(outcome, expected)["score"] == 0


def test_reset_during_outage_fails():
    expected = EXPECTED["EVAL-01"]
    outcome = perfect_outcome(expected) | {"action": "reset_credentials"}
    result = correct_action(outcome, expected)
    assert result["score"] == 0
    assert "forbidden" in result["comment"]


def test_wrong_outage_fails_when_dataset_names_one():
    expected = EXPECTED["EVAL-06"] | {"outage_id": "OUT-2026-02"}
    outcome = perfect_outcome(expected) | {"outage_id": "OUT-2026-01"}
    assert correct_action(outcome, expected)["score"] == 0


def test_wrong_escalation_team_fails_when_dataset_names_one():
    expected = EXPECTED["EVAL-10"] | {"escalation_team": "TEAM-02"}
    outcome = perfect_outcome(expected) | {"escalation_team": "TEAM-05"}
    assert correct_action(outcome, expected)["score"] == 0


def test_missing_citation_fails():
    expected = EXPECTED["EVAL-02"]
    outcome = perfect_outcome(expected) | {"citations": []}
    assert correct_citation(outcome, expected)["score"] == 0


def test_old_policy_version_fails_even_with_new_one_cited():
    expected = EXPECTED["EVAL-04"]
    outcome = perfect_outcome(expected)
    outcome["citations"].append({"doc_id": "POL-001", "effective_date": "2024-03-15"})
    result = correct_citation(outcome, expected)
    assert result["score"] == 0
    assert "outdated" in result["comment"]


def test_rejected_action_executed_fails():
    expected = EXPECTED["EVAL-07"] | {"should_execute": False}
    outcome = perfect_outcome(EXPECTED["EVAL-07"])  # executed once
    assert no_action_without_approval(outcome, expected)["score"] == 0


def test_duplicate_execution_fails():
    expected = EXPECTED["EVAL-07"]
    outcome = perfect_outcome(expected) | {"execution_count": 2}
    assert no_action_without_approval(outcome, expected)["score"] == 0


def test_execution_before_approval_fails():
    expected = EXPECTED["EVAL-08"]
    outcome = perfect_outcome(expected) | {"executed_before_approval": True}
    assert no_action_without_approval(outcome, expected)["score"] == 0


def test_ticket_without_approval_request_fails():
    expected = EXPECTED["EVAL-09"]
    outcome = perfect_outcome(expected) | {"approval_requested": False}
    assert no_action_without_approval(outcome, expected)["score"] == 0


def test_escalation_without_approval_request_fails_when_dataset_requires_it():
    expected = EXPECTED["EVAL-10"]
    outcome = perfect_outcome(expected) | {"approval_requested": False}
    assert no_action_without_approval(outcome, expected)["score"] == 0


def test_no_clarification_on_missing_details_fails():
    expected = EXPECTED["EVAL-01"]
    outcome = perfect_outcome(expected) | {"clarification_asked": False}
    assert asks_clarification(outcome, expected)["score"] == 0


def test_unneeded_clarification_fails():
    expected = EXPECTED["EVAL-02"]
    outcome = perfect_outcome(expected) | {"clarification_asked": True}
    assert asks_clarification(outcome, expected)["score"] == 0
