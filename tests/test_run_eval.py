"""The evaluation runner drives the real graph and builds the outcome the evaluators read.

These tests check the runner, not the graph's score: failing examples are reported by
`python -m eval.run_eval` and turned into issues for the owning role.
"""

from types import SimpleNamespace

import pytest

from eval.dataset import load_examples
from eval.evaluators import RunOutcome, correct_action, evaluate
from eval.run_eval import _langsmith_evaluator, run_example
from eval.upload_dataset import DEFAULT_DATASET_NAME, dataset_name
from src.agent.graph import build_graph

EXAMPLES = {e["metadata"]["id"]: e for e in load_examples()}


@pytest.fixture(scope="module")
def graph():
    return build_graph()


@pytest.mark.parametrize("example_id", sorted(EXAMPLES))
def test_every_example_runs_and_is_scored(graph, example_id):
    example = EXAMPLES[example_id]
    outcome, _ = run_example(graph, example["inputs"])
    assert set(RunOutcome.__annotations__) <= set(outcome)
    results = evaluate(outcome, example["outputs"])
    assert {r["key"] for r in results} == {
        "correct_action", "correct_citation", "no_action_without_approval", "asks_clarification"
    }


def test_approved_reset_is_requested_and_executed_once(graph):
    outcome, log = run_example(graph, EXAMPLES["EVAL-07"]["inputs"])
    assert outcome["action_type"] == "reset_credentials"
    assert outcome["approval_requested"]
    assert outcome["execution_count"] == 1
    assert not outcome["executed_before_approval"]
    assert any(line.startswith("approval for reset_credentials") for line in log)


def test_policy_question_needs_no_approval(graph):
    outcome, _ = run_example(graph, EXAMPLES["EVAL-02"]["inputs"])
    assert outcome["action_type"] == "answer_policy"
    assert not outcome["approval_requested"]
    assert outcome["execution_count"] == 0
    assert outcome["citations"] == [{"doc_id": "POL-016", "effective_date": "2026-01-05"}]


def test_rejected_action_is_not_executed(graph):
    inputs = EXAMPLES["EVAL-07"]["inputs"] | {"approval_decision": "rejected"}
    outcome, _ = run_example(graph, inputs)
    assert outcome["approval_requested"]
    assert outcome["execution_count"] == 0
    assert outcome["action_status"] == "rejected"


def test_langsmith_adapter_passes_run_and_example_outputs():
    wrapped = _langsmith_evaluator(correct_action)
    run = SimpleNamespace(outputs={"action_type": "open_ticket"})
    example = SimpleNamespace(outputs={"expected_action": "open_ticket", "forbidden_actions": []})
    assert wrapped.__name__ == "correct_action"
    assert wrapped(run, example)["score"] == 1


def test_dataset_name_default(monkeypatch):
    monkeypatch.delenv("LANGSMITH_DATASET", raising=False)
    assert dataset_name() == DEFAULT_DATASET_NAME
