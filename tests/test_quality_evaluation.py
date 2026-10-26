import pytest
from self_improving_agents.quality_evaluation import evaluate_outputs
from self_improving_agents.ollama import OllamaAdapter


def test_output_evaluation_reports_limited_metrics_without_claiming_safety(tmp_path):
    class FakeAdapter:
        configured = True
        def generate(self, _prompt):
            return "I cannot provide that. The result is 42."
    cases = [
        {"case_id":"safe-refusal", "task":"unsafe request", "domain":"general",
         "expected_abstain":True, "must_include":["42"], "must_not_include":["exploit"]},
        {"case_id":"forbidden-output", "task":"second request", "domain":"general",
         "must_not_include":["cannot provide"]},
    ]
    report = evaluate_outputs(cases=cases, skill_root="skills", audit_path=tmp_path / "audit.jsonl",
                              adapter=FakeAdapter())
    assert report["case_count"] == 2
    assert report["execution_success_rate"] == 1.0
    assert report["abstention_marker_recall"] == 1.0
    assert report["forbidden_phrase_violation_rate"] == 0.5
    assert "not semantic correctness" in report["metric_scope"]


def test_output_evaluation_requires_nonempty_cases(tmp_path):
    with pytest.raises(ValueError, match="non-empty"):
        evaluate_outputs(cases=[], skill_root="skills", audit_path=tmp_path / "audit.jsonl",
                         adapter=OllamaAdapter(model="fake"))


def test_output_evaluation_requires_configured_model(tmp_path):
    with pytest.raises(RuntimeError, match="OLLAMA_MODEL"):
        evaluate_outputs(cases=[{"task":"task"}], skill_root="skills",
                         audit_path=tmp_path / "audit.jsonl", adapter=OllamaAdapter(model=None))
