from self_improving_agents.evaluation import evaluate_routing, load_jsonl
from self_improving_agents.skills import discover_skills


def test_routing_smoke_fixture_reports_metrics():
    cases = load_jsonl("eval/routing_smoke.jsonl")
    report = evaluate_routing(cases, discover_skills("skills"), top_k=3)
    assert report["case_count"] == 6
    assert report["top1_accuracy"] == 1.0
    assert report["topk_recall"] == 1.0
    assert report["metric_scope"].startswith("routing-label agreement only")


def test_evaluation_rejects_empty_dataset():
    import pytest
    with pytest.raises(ValueError, match="at least one"):
        evaluate_routing([], discover_skills("skills"))
