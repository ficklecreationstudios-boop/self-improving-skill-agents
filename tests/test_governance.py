import pytest
from dataclasses import replace
from self_improving_agents.audit import AuditLedger
from self_improving_agents.agents.review import propose_skill_update
from self_improving_agents.governance.approval import Governance, GovernanceError

def setup_governance(tmp_path, content="---\nid: demo\n---\nold"):
    root = tmp_path / "skills"; folder = root / "demo"; folder.mkdir(parents=True)
    target = folder / "SKILL.md"; target.write_text(content)
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    return target, ledger, Governance(root, tmp_path / "archive", ledger)

def test_update_requires_matching_approval_and_archives(tmp_path):
    target, ledger, gov = setup_governance(tmp_path)
    original = target.read_text()
    proposal = propose_skill_update("demo", original, "---\nid: demo\n---\nnew", "test improvement")
    approval = gov.issue_approval(proposal, "human", True)
    with pytest.raises(GovernanceError): gov.apply(proposal, replace(approval, proposal_digest="wrong"))
    gov.apply(proposal, approval)
    assert "new" in target.read_text() and list((tmp_path / "archive").glob("*.SKILL.md"))
    assert ledger.verify()

def test_rejects_unapproved_proposal(tmp_path):
    target, ledger, gov = setup_governance(tmp_path)
    proposal = propose_skill_update("demo", target.read_text(), "new", "why")
    with pytest.raises(GovernanceError): gov.apply(proposal, gov.issue_approval(proposal, "human", False))

def test_rejects_stale_base_even_with_valid_approval(tmp_path):
    target, _, gov = setup_governance(tmp_path)
    proposal = propose_skill_update("demo", target.read_text(), "new", "why")
    approval = gov.issue_approval(proposal, "human", True)
    target.write_text("changed since proposal")
    with pytest.raises(GovernanceError, match="Stale proposal"):
        gov.apply(proposal, approval)
