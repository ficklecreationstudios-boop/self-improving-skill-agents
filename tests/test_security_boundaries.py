from __future__ import annotations
import json
import pytest

from self_improving_agents.audit import AuditIntegrityError, AuditLedger
from self_improving_agents.agents.review import propose_skill_update
from self_improving_agents.governance.approval import Governance, GovernanceError


def test_corrupted_audit_fails_closed_and_cannot_be_appended(tmp_path):
    path = tmp_path / "audit.jsonl"
    ledger = AuditLedger(path)
    ledger.append("baseline", {"ok": True})
    event = json.loads(path.read_text().splitlines()[0])
    event["payload"]["ok"] = False
    path.write_text(json.dumps(event) + "\n", encoding="utf-8")

    assert ledger.verify() is False
    with pytest.raises(AuditIntegrityError, match="integrity"):
        ledger.append("must_not_append", {})


def test_malformed_audit_is_reported_invalid_not_crashed(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text('{"partial":\n', encoding="utf-8")
    assert AuditLedger(path).verify() is False


def test_duplicate_skill_ids_are_rejected_before_any_update(tmp_path):
    root = tmp_path / "skills"
    first = root / "one"; first.mkdir(parents=True)
    second = root / "two"; second.mkdir(parents=True)
    content = "---\nid: demo\n---\nold"
    (first / "SKILL.md").write_text(content, encoding="utf-8")
    (second / "SKILL.md").write_text(content, encoding="utf-8")
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    governance = Governance(root, tmp_path / "archive", ledger)
    proposal = propose_skill_update("demo", content, "new content", "test")
    approval = governance.issue_approval(proposal, "reviewer", True)

    with pytest.raises(GovernanceError, match="exactly one"):
        governance.apply(proposal, approval)
    assert (first / "SKILL.md").read_text(encoding="utf-8") == content
    assert (second / "SKILL.md").read_text(encoding="utf-8") == content
    assert list((tmp_path / "archive").glob("*")) == []


def test_invalid_audit_blocks_skill_update(tmp_path):
    root = tmp_path / "skills"
    folder = root / "demo"; folder.mkdir(parents=True)
    content = "---\nid: demo\n---\nold"
    target = folder / "SKILL.md"; target.write_text(content, encoding="utf-8")
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    ledger.append("baseline", {"ok": True})
    ledger.path.write_text("not-json\n", encoding="utf-8")
    governance = Governance(root, tmp_path / "archive", ledger)
    proposal = propose_skill_update("demo", content, "new content", "test")
    approval = governance.issue_approval(proposal, "reviewer", True)

    with pytest.raises(GovernanceError, match="Audit ledger"):
        governance.apply(proposal, approval)
    assert target.read_text(encoding="utf-8") == content
