"""Execution counting used by the restart scenario (eval/restart_scenario.py), without Docker."""

import uuid

from eval.restart_scenario import REQUEST, SENDER, count_executions
from src.agent.graph import build_graph, config_for, decide, pending, start


def test_counts_one_execution_and_ignores_replays():
    graph = build_graph()
    config = config_for(f"restart-{uuid.uuid4().hex[:8]}", SENDER)

    start(graph, config, REQUEST)
    assert pending(graph, config) == "approval"
    assert count_executions(graph, config) == 0

    decide(graph, config, approved=True)
    assert count_executions(graph, config) == 1

    graph.invoke(None, config)  # replay of the finished thread
    assert count_executions(graph, config) == 1


def test_rejected_action_counts_no_execution():
    graph = build_graph()
    config = config_for(f"restart-{uuid.uuid4().hex[:8]}", SENDER)
    start(graph, config, REQUEST)
    decide(graph, config, approved=False)
    assert count_executions(graph, config) == 0
