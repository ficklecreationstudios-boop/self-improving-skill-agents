import json
import pytest
from self_improving_agents.quality_evaluation import evaluate_outputs, evaluate_file
from self_improving_agents.ollama import OllamaAdapter
from self_improving_agents.audit import AuditLedger


class FakeAdapter:
    configured = True
    def generate(self, _prompt):
        return "I cannot provide that. The result is 42."


def test_output_evaluation_reports_limited_metrics_without_claiming_safety(tmp_path):
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


def test_thresholds_must_be_preregistered_and_are_audited(tmp_path):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps({"case_id":"one","task":"task","must_include":["42"]}) + "\n", encoding="utf-8")
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(json.dumps({"minimum_execution_success_rate":1.0,
                                      "minimum_required_phrase_pass_rate":1.0}), encoding="utf-8")
    report_path = tmp_path / "report.json"
    audit_path = tmp_path / "audit.jsonl"
    report = evaluate_file(cases, "skills", audit_path, FakeAdapter(), report_path, thresholds)
    assert report["preregistration"]["recorded_before_model_run"] is True
    assert report["gate"]["passed"] is True
    assert report_path.exists()
    events = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert events[0]["type"] == "quality_evaluation_preregistered"
    assert events[-1]["type"] == "quality_evaluation_completed"
    assert AuditLedger(audit_path).verify()


def test_evaluation_requires_threshold_file(tmp_path):
    with pytest.raises(ValueError, match="threshold file"):
        evaluate_file(tmp_path / "missing.jsonl", "skills", tmp_path / "audit.jsonl",
                      FakeAdapter(), thresholds_path=None)
