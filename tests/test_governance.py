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
    approval = gov.issue_approval(proposal, "reviewer", True, "reviewed stale-base test")
    target.write_text("changed since proposal")
    with pytest.raises(GovernanceError, match="Stale proposal"):
        gov.apply(proposal, approval)


def test_wrong_key_cannot_authorize_update(tmp_path):
    target, _, gov = setup_governance(tmp_path)
    proposal = propose_skill_update("demo", target.read_text(), "new", "why")
    signed_by_other_key = Governance(tmp_path / "skills", tmp_path / "archive",
                                     AuditLedger(tmp_path / "audit.jsonl"),
                                     approval_key=b"different-key-material-32-bytes-minimum!!")
    approval = signed_by_other_key.issue_approval(proposal, "reviewer", True, "reviewed")
    with pytest.raises(GovernanceError, match="signature"):
        gov.apply(proposal, approval)


def test_short_key_is_rejected(tmp_path):
    target, _, gov = setup_governance(tmp_path, key=b"short")
    proposal = propose_skill_update("demo", target.read_text(), "new", "why")
    with pytest.raises(GovernanceError, match="32 random bytes"):
        gov.issue_approval(proposal, "reviewer", True, "reviewed")


def test_signed_approval_cannot_authorize_a_different_proposal(tmp_path):
    target, ledger, gov = setup_governance(tmp_path)
    original = target.read_text(encoding="utf-8")
    approved_proposal = propose_skill_update(
        "demo", original, "---\nid: demo\n---\napproved content", "approved change"
    )
    approval = gov.issue_approval(approved_proposal, "reviewer", True, "reviewed exact change")
    different_proposal = propose_skill_update(
        "demo", original, "---\nid: demo\n---\ndifferent content", "different change"
    )

    with pytest.raises(GovernanceError, match="does not bind this exact proposal"):
        gov.apply(different_proposal, approval)

    assert target.read_text(encoding="utf-8") == original
    assert list((tmp_path / "archive").glob("*.SKILL.md")) == []
    assert ledger.verify()


def test_approval_signature_binds_key_identifier(tmp_path):
    target, ledger, gov = setup_governance(tmp_path)
    original = target.read_text(encoding="utf-8")
    proposal = propose_skill_update("demo", original, "---\\nid: demo\\n---\\nnew", "key-id binding")
    approval = gov.issue_approval(proposal, "reviewer", True, "reviewed key id")
    assert len(approval.key_id) == 64
    with pytest.raises(GovernanceError, match="key identifier"):
        gov.apply(proposal, replace(approval, key_id="0" * 64))
    assert target.read_text(encoding="utf-8") == original
    assert ledger.verify()


def test_revoked_key_cannot_sign_or_apply_approval(tmp_path):
    target, ledger, gov = setup_governance(tmp_path)
    original = target.read_text(encoding="utf-8")
    proposal = propose_skill_update("demo", original, "---\\nid: demo\\n---\\nnew", "revocation")
    approval = gov.issue_approval(proposal, "reviewer", True, "signed before revocation")
    ledger.append("approval_key_revoked", {"key_id": approval.key_id, "reason": "test revocation"})
    with pytest.raises(GovernanceError, match="revoked"):
        gov.apply(proposal, approval)
    with pytest.raises(GovernanceError, match="revoked"):
        gov.issue_approval(proposal, "reviewer", True, "try after revocation")
    assert target.read_text(encoding="utf-8") == original
    assert ledger.verify()


def test_key_revocation_is_audited_idempotent_and_serialized(tmp_path):
    target, ledger, gov = setup_governance(tmp_path)
    original = target.read_text(encoding="utf-8")
    proposal = propose_skill_update("demo", original, "---\\nid: demo\\n---\\nnew", "revocation API")
    approval = gov.issue_approval(proposal, "reviewer", True, "reviewed before revocation")
    result = gov.revoke_approval_key(approval.key_id, "rotate compromised test key")
    assert result["status"] == "key_revoked"
    assert ledger.verify()
    assert gov.revoke_approval_key(approval.key_id, "repeat revocation")["status"] == "already_revoked"
    with pytest.raises(GovernanceError, match="revoked"):
        gov.apply(proposal, approval)
    assert target.read_text(encoding="utf-8") == original


def test_key_revocation_rejects_invalid_identifier_and_empty_reason(tmp_path):
    _, _, gov = setup_governance(tmp_path)
    with pytest.raises(GovernanceError, match="64-character"):
        gov.revoke_approval_key("not-a-key-id", "reason")
    with pytest.raises(GovernanceError, match="reason"):
        gov.revoke_approval_key("a" * 64, "  ")
