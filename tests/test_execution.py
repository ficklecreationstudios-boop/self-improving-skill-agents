from self_improving_agents.models import Task
from self_improving_agents.orchestrator import run_task
from self_improving_agents.ollama import OllamaAdapter

def test_no_model_fallback_is_explicit_and_audited(tmp_path):
    result = run_task(Task("Explain the project"), "skills", tmp_path / "audit.jsonl", OllamaAdapter(model=None))
    assert "No Ollama model configured" in result.output
    assert result.review.verdict == "generated"
