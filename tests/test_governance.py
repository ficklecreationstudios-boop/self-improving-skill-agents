import pytest
from dataclasses import replace
from self_improving_agents.audit import AuditLedger
from self_improving_agents.agents.review import propose_skill_update
from self_improving_agents.governance.approval import Governance, GovernanceError

KEY = b"test-only-approval-key-material-32-bytes-minimum!!"


def setup_governance(tmp_path, content="---\nid: demo\n---\nold", key=KEY):
    root = tmp_path / "skills"; folder = root / "demo"; folder.mkdir(parents=True)
    target = folder / "SKILL.md"; target.write_text(content)
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    return target, ledger, Governance(root, tmp_path / "archive", ledger, approval_key=key)


def test_update_requires_valid_signed_approval_and_archives(tmp_path):
    target, ledger, gov = setup_governance(tmp_path)
    original = target.read_text()
    proposal = propose_skill_update("demo", original, "---\nid: demo\n---\nnew", "test improvement")
    approval = gov.issue_approval(proposal, "reviewer", True, "reviewed")
    with pytest.raises(GovernanceError, match="signature"):
        gov.apply(proposal, replace(approval, signature="00" * 32))
    gov.apply(proposal, approval)
    assert "new" in target.read_text() and list((tmp_path / "archive").glob("*.SKILL.md"))
    assert ledger.verify()


def test_rejects_unapproved_proposal(tmp_path):
    target, _, gov = setup_governance(tmp_path)
    proposal = propose_skill_update("demo", target.read_text(), "new", "why")
    approval = gov.issue_approval(proposal, "reviewer", False)
    with pytest.raises(GovernanceError, match="signature"):
        gov.apply(proposal, approval)


def test_rejects_stale_base_even_with_valid_signed_approval(tmp_path):
    target, _, gov = setup_governance(tmp_path)
    proposal = propose_skill_update("demo", target.read_text(), "new", "why")
    approval = gov.issue_approval(proposal, "reviewer", True)
    target.write_text("changed since proposal")
    with pytest.raises(GovernanceError, match="Stale proposal"):
        gov.apply(proposal, approval)


def test_wrong_key_cannot_authorize_update(tmp_path):
    target, _, gov = setup_governance(tmp_path)
    proposal = propose_skill_update("demo", target.read_text(), "new", "why")
    signed_by_other_key = Governance(tmp_path / "skills", tmp_path / "archive",
                                     AuditLedger(tmp_path / "audit.jsonl"),
                                     approval_key=b"different-key-material-32-bytes-minimum!!")
    approval = signed_by_other_key.issue_approval(proposal, "reviewer", True)
    with pytest.raises(GovernanceError, match="signature"):
        gov.apply(proposal, approval)


def test_short_key_is_rejected(tmp_path):
    target, _, gov = setup_governance(tmp_path, key=b"short")
    proposal = propose_skill_update("demo", target.read_text(), "new", "why")
    with pytest.raises(GovernanceError, match="32 random bytes"):
        gov.issue_approval(proposal, "reviewer", True)
