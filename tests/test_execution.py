import json
import pytest
from self_improving_agents.models import Task
from self_improving_agents.orchestrator import run_task, ModelNotConfiguredError
from self_improving_agents.ollama import OllamaAdapter


def test_unconfigured_model_is_not_misreported_as_completed(tmp_path):
    audit = tmp_path / "audit.jsonl"
    with pytest.raises(ModelNotConfiguredError, match="no model inference was performed"):
        run_task(Task("Explain the project"), "skills", audit, OllamaAdapter(model=None))
    events = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 1
    assert events[0]["type"] == "task_not_executed"
    assert events[0]["payload"]["reason"] == "ollama_model_not_configured"
