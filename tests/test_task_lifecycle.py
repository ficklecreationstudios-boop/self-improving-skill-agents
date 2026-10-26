import json

import pytest

from self_improving_agents.audit import AuditLedger
from self_improving_agents.models import Task, digest_text
from self_improving_agents.orchestrator import run_task


class FakeAdapter:
    configured = True

    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.prompt = None

    def generate(self, prompt):
        self.prompt = prompt
        if self.error is not None:
            raise self.error
        return self.output


def make_skill_root(tmp_path):
    root = tmp_path / "skills"
    folder = root / "demo"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        "---\nid: demo\nname: Python Testing\ndomain: engineering\ntags: [python, testing]\n---\n"
        "Use focused regression tests and explain the observed failure.\n",
        encoding="utf-8",
    )
    return root


def read_events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_task_lifecycle_routes_generates_reviews_delivers_and_audits(tmp_path):
    skills = make_skill_root(tmp_path)
    audit_path = tmp_path / "audit.jsonl"
    adapter = FakeAdapter(output="The regression test fails because the expected value is wrong.")
    task = Task("Debug Python testing", domain="engineering", task_id="task-success")

    result = run_task(task, skills, audit_path, adapter)

    assert result.output == adapter.output
    assert result.skill_ids == ["demo"]
    assert "[Skill: Python Testing]" in adapter.prompt
    assert "Use focused regression tests" in adapter.prompt
    assert result.review.verdict == "generated"
    assert result.task_digest == digest_text(task.text)
    assert result.output_digest == digest_text(adapter.output)

    events = read_events(audit_path)
    assert len(events) == 1
    assert events[0]["type"] == "task_completed"
    assert events[0]["payload"]["task_id"] == "task-success"
    assert events[0]["payload"]["skills"] == ["demo"]
    assert events[0]["payload"]["task_digest"] == result.task_digest
    assert events[0]["payload"]["output_digest"] == result.output_digest
    assert events[0]["payload"]["review_verdict"] == "generated"
    assert AuditLedger(audit_path).verify()


def test_task_lifecycle_audits_generation_failure_and_reraises(tmp_path):
    skills = make_skill_root(tmp_path)
    audit_path = tmp_path / "audit.jsonl"
    adapter = FakeAdapter(error=RuntimeError("simulated inference failure"))
    task = Task("Debug Python testing", domain="engineering", task_id="task-failed")

    with pytest.raises(RuntimeError, match="simulated inference failure"):
        run_task(task, skills, audit_path, adapter)

    events = read_events(audit_path)
    assert len(events) == 1
    assert events[0]["type"] == "task_execution_failed"
    assert events[0]["payload"]["task_id"] == "task-failed"
    assert events[0]["payload"]["error_type"] == "RuntimeError"
    assert events[0]["payload"]["error"] == "simulated inference failure"
    assert events[0]["payload"]["skills"] == ["demo"]
    assert AuditLedger(audit_path).verify()
