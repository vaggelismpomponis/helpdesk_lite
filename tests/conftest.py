"""Shared test setup."""

import pytest


@pytest.fixture(autouse=True)
def no_live_llm(monkeypatch):
    """Keep tests deterministic and free: never call a real chat model, even if .env has API keys.

    Tests that exercise the LLM path patch `src.agent.nodes.get_llm` with a fake model.
    """
    monkeypatch.setenv("LLM_PROVIDER", "offline")
