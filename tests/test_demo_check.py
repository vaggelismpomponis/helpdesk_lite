"""Demo requests (eval/demo_check.py) give the outcomes the demo script expects, without Docker."""

import pytest

from eval.demo_check import DEMO_STEPS, run_step
from src.agent.graph import build_graph


@pytest.mark.parametrize("step", DEMO_STEPS, ids=lambda s: s.segment)
def test_demo_step(step):
    assert run_step(build_graph(), step) == []
