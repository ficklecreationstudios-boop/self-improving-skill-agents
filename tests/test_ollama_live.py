"""Opt-in integration test against an actual local Ollama instance.

Run only on a machine with Ollama running and OLLAMA_MODEL configured:
RUN_OLLAMA_INTEGRATION=1 pytest -q tests/test_ollama_live.py
"""
import os
import pytest
from self_improving_agents.ollama import OllamaAdapter

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OLLAMA_INTEGRATION") != "1" or not os.getenv("OLLAMA_MODEL"),
    reason="Set RUN_OLLAMA_INTEGRATION=1 and OLLAMA_MODEL to run live local inference",
)


def test_live_ollama_returns_nonempty_model_output():
    adapter = OllamaAdapter(timeout=90)
    result = adapter.generate("Reply with exactly the word READY.")
    assert result.strip()
    assert "No Ollama model configured" not in result
