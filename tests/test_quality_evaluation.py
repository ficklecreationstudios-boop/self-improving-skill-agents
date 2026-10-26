import json
import pytest
from self_improving_agents.quality_evaluation import evaluate_outputs, evaluate_file, _wilson_interval
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
    assert report["abstention_marker_precision"] == 0.5
    assert report["abstention_marker_detection_count"] == 2
    assert report["forbidden_phrase_violation_rate"] == 0.5
    assert "not semantic correctness" in report["metric_scope"]


def test_output_evaluation_reports_domain_metrics_and_wilson_intervals(tmp_path):
    cases = [
        {"case_id":"general-one", "task":"first", "domain":"general", "must_include":["42"]},
        {"case_id":"safety-one", "task":"unsafe", "domain":"safety", "expected_abstain":True,
         "must_not_include":["exploit"]},
    ]
    report = evaluate_outputs(cases=cases, skill_root="skills", audit_path=tmp_path / "audit.jsonl",
                              adapter=FakeAdapter())
    assert report["schema_version"] == 2
    assert report["domain_metrics"]["general"]["case_count"] == 1
    assert report["domain_metrics"]["general"]["required_phrase_pass_rate"] == 1.0
    assert report["domain_metrics"]["safety"]["abstention_marker_recall"] == 1.0
    assert report["domain_metrics"]["safety"]["abstention_marker_precision"] == 1.0
    interval = report["metric_confidence_intervals_95"]["execution_success_rate"]
    assert interval["successes"] == 2 and interval["trials"] == 2
    assert interval["lower_95"] < interval["estimate"] <= interval["upper_95"]
    assert interval["upper_95"] <= 1.0
    assert "Wilson" in interval["method"]


def test_wilson_interval_handles_no_eligible_cases_and_validates_counts():
    assert _wilson_interval(0, 0) is None
    with pytest.raises(ValueError, match="between zero and trials"):
        _wilson_interval(2, 1)


def test_output_evaluation_rejects_duplicate_case_ids_before_running_model(tmp_path):
    class MustNotRunAdapter:
        configured = True
        def generate(self, _prompt):
            raise AssertionError("model must not run for invalid case IDs")
    cases = [
        {"case_id":"duplicate", "task":"first"},
        {"case_id":"duplicate", "task":"second"},
    ]
    with pytest.raises(ValueError, match="duplicate evaluation case_id"):
        evaluate_outputs(cases=cases, skill_root="skills", audit_path=tmp_path / "audit.jsonl",
                         adapter=MustNotRunAdapter())


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
