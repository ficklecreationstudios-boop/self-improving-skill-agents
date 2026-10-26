import pytest
from dataclasses import replace
from self_improving_agents.audit import AuditLedger
from self_improving_agents.agents.review import propose_skill_update
from self_improving_agents.governance.approval import Governance, GovernanceError

def test_update_requires_matching_approval_and_archives(tmp_path):
    root = tmp_path / "skills"; folder = root / "demo"; folder.mkdir(parents=True)
    target = folder / "SKILL.md"; original = "---\nid: demo\n---\nold"
    target.write_text(original)
    ledger = AuditLedger(tmp_path / "audit.jsonl"); gov = Governance(root, tmp_path / "archive", ledger)
    proposal = propose_skill_update("demo", original, "---\nid: demo\n---\nnew", "test improvement")
    approval = gov.issue_approval(proposal, "human", True)
    with pytest.raises(GovernanceError): gov.apply(proposal, replace(approval, proposal_digest="wrong"))
    gov.apply(proposal, approval)
    assert "new" in target.read_text() and list((tmp_path / "archive").glob("*.SKILL.md"))
    assert ledger.verify()

def test_rejects_unapproved_proposal(tmp_path):
    root = tmp_path / "skills"; folder = root / "demo"; folder.mkdir(parents=True)
    original = "---\nid: demo\n---\nold"; (folder / "SKILL.md").write_text(original)
    gov = Governance(root, tmp_path / "archive", AuditLedger(tmp_path / "audit.jsonl"))
    proposal = propose_skill_update("demo", original, "new", "why")
    with pytest.raises(GovernanceError): gov.apply(proposal, gov.issue_approval(proposal, "human", False))
