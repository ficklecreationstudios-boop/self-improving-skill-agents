"""D4.3/D10 approver policy with key rotation, and F7 audit anchors."""
import json
import os
import sys

import pytest

from self_improving_agents import approver_policy, audit_anchor, cli
from self_improving_agents.approval_auth import key_identifier
from self_improving_agents.audit import AuditLedger
from self_improving_agents.governance.approval import Governance, GovernanceError
from self_improving_agents.models import digest_text, Proposal
from self_improving_agents.owner_only import owner_only_problem

KEY_A, KEY_B = b"a" * 32, b"b" * 32
SKILL = "---\nid: general\n---\nOriginal.\n"


@pytest.fixture
def setting(tmp_path):
    skill = tmp_path / "skills" / "general" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(SKILL, encoding="utf-8")

    def governance(key):
        return Governance(tmp_path / "skills", tmp_path / "archive", AuditLedger(tmp_path / "audit.jsonl"), approval_key=key)

    def proposal(text="Updated."):
        return Proposal("general", digest_text(SKILL), SKILL.replace("Original.", text), "test").sealed()

    return governance, proposal, skill


def _events(tmp_path):
    return AuditLedger(tmp_path / "audit.jsonl")._events()


def test_without_a_policy_the_single_operator_default_is_recorded(setting, tmp_path):
    governance, proposal, _ = setting
    governance(KEY_A).issue_approval(proposal(), "anyone", True, "ok")
    assert _events(tmp_path)[-1]["payload"]["authorized_by"] == approver_policy.SINGLE_OPERATOR


def test_a_listed_key_and_name_can_sign_and_apply(setting, tmp_path):
    governance, proposal, skill = setting
    approver_policy.add_approver(key_identifier(KEY_A), "owner")
    approval = governance(KEY_A).issue_approval(proposal(), "owner", True, "ok")
    assert _events(tmp_path)[-1]["payload"]["authorized_by"] == approver_policy.LISTED
    governance(KEY_A).apply(proposal(), approval)
    assert "Updated." in skill.read_text(encoding="utf-8")


@pytest.mark.parametrize("key, name", [(KEY_B, "owner"), (KEY_A, "someone-else")])
def test_an_unlisted_key_or_name_cannot_sign(setting, tmp_path, key, name):
    governance, proposal, _ = setting
    approver_policy.add_approver(key_identifier(KEY_A), "owner")
    with pytest.raises(GovernanceError, match="not listed"):
        governance(key).issue_approval(proposal(), name, True, "ok")
    assert _events(tmp_path) == []


def test_apply_rechecks_the_policy_after_signing(setting):
    """An approval signed before the key was dropped from the policy must not apply."""
    governance, proposal, skill = setting
    approval = governance(KEY_A).issue_approval(proposal(), "owner", True, "ok")
    approver_policy.add_approver(key_identifier(KEY_B), "second")
    with pytest.raises(GovernanceError, match="not listed"):
        governance(KEY_A).apply(proposal(), approval)
    assert skill.read_text(encoding="utf-8") == SKILL


def test_key_rotation_new_key_works_and_old_key_is_refused(setting):
    governance, proposal, skill = setting
    old, new = key_identifier(KEY_A), key_identifier(KEY_B)
    approver_policy.add_approver(old, "owner")
    pending = governance(KEY_A).issue_approval(proposal(), "owner", True, "before rotation")
    approver_policy.add_approver(new, "owner")
    governance(KEY_A).revoke_approval_key(old, "rotated")
    with pytest.raises(GovernanceError, match="revoked"):
        governance(KEY_A).issue_approval(proposal("Again."), "owner", True, "old key")
    with pytest.raises(GovernanceError, match="revoked"):
        governance(KEY_A).apply(proposal(), pending)
    assert skill.read_text(encoding="utf-8") == SKILL
    fresh = proposal("Rotated.")
    governance(KEY_B).apply(fresh, governance(KEY_B).issue_approval(fresh, "owner", True, "new key"))
    assert "Rotated." in skill.read_text(encoding="utf-8")


@pytest.mark.parametrize("content", ["not json", "{}", '{"schema": "approver-policy/1", "approvers": [{"key_id": "short", "name": "x"}]}'])
def test_a_malformed_policy_fails_closed(setting, content):
    governance, proposal, _ = setting
    approver_policy.add_approver(key_identifier(KEY_A), "owner")
    approver_policy.policy_path().write_text(content, encoding="utf-8")
    with pytest.raises(GovernanceError, match="malformed|Cannot read"):
        governance(KEY_A).issue_approval(proposal(), "owner", True, "ok")


def test_the_policy_file_is_owner_only_and_refused_when_it_is_not(setting):
    governance, proposal, _ = setting
    approver_policy.add_approver(key_identifier(KEY_A), "owner")
    path = approver_policy.policy_path()
    assert owner_only_problem(path) is None
    if os.name == "nt":
        import subprocess
        subprocess.run(["icacls", str(path), "/grant", "*S-1-1-0:(R)"], capture_output=True, check=True)
    else:
        path.chmod(0o644)
    with pytest.raises(GovernanceError, match="not owner-only"):
        governance(KEY_A).issue_approval(proposal(), "owner", True, "ok")


@pytest.mark.parametrize("key_id, name", [("short", "owner"), ("a" * 64, "  ")])
def test_add_approver_rejects_bad_input(key_id, name):
    with pytest.raises(approver_policy.ApproverPolicyError):
        approver_policy.add_approver(key_id, name)


def test_adding_the_same_approver_twice_changes_nothing():
    key_id = key_identifier(KEY_A)
    approver_policy.add_approver(key_id, "owner")
    assert approver_policy.add_approver(key_id, "owner")["status"] == "already_listed"
    assert len(approver_policy.list_approvers()) == 1


def _ledger(tmp_path, count=3):
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    for index in range(count):
        ledger.append("event", {"index": index})
    return ledger


def _rebuild(path, count):
    """The F7 attack: replace the whole file with a fresh chain that verifies."""
    path.unlink()
    rebuilt = AuditLedger(path)
    for index in range(count):
        rebuilt.append("forged", {"index": index})
    assert rebuilt.verify() is True


def test_an_anchor_notices_a_full_rewrite_that_the_chain_cannot(tmp_path):
    _ledger(tmp_path)
    audit_anchor.record_anchor(tmp_path / "audit.jsonl")
    assert audit_anchor.anchor_problems(tmp_path / "audit.jsonl") == []
    _rebuild(tmp_path / "audit.jsonl", 3)
    assert "rewritten" in audit_anchor.anchor_problems(tmp_path / "audit.jsonl")[0]


def test_an_anchor_notices_truncation(tmp_path):
    _ledger(tmp_path)
    audit_anchor.record_anchor(tmp_path / "audit.jsonl")
    _rebuild(tmp_path / "audit.jsonl", 2)
    assert "missing" in audit_anchor.anchor_problems(tmp_path / "audit.jsonl")[0]


def test_new_events_after_an_anchor_are_fine(tmp_path):
    ledger = _ledger(tmp_path)
    audit_anchor.record_anchor(tmp_path / "audit.jsonl")
    ledger.append("later", {})
    assert audit_anchor.anchor_problems(tmp_path / "audit.jsonl") == []


def test_every_earlier_anchor_still_counts(tmp_path):
    ledger = _ledger(tmp_path)
    audit_anchor.record_anchor(tmp_path / "audit.jsonl")
    ledger.append("later", {})
    audit_anchor.record_anchor(tmp_path / "audit.jsonl")
    assert len(json.loads(audit_anchor.anchors_path().read_text(encoding="utf-8"))["anchors"]) == 2
    _rebuild(tmp_path / "audit.jsonl", 4)
    assert len(audit_anchor.anchor_problems(tmp_path / "audit.jsonl")) == 2


def test_anchors_are_kept_per_ledger(tmp_path):
    _ledger(tmp_path)
    audit_anchor.record_anchor(tmp_path / "audit.jsonl")
    other = AuditLedger(tmp_path / "other.jsonl")
    other.append("event", {})
    assert audit_anchor.anchor_problems(tmp_path / "other.jsonl") == []


def test_an_empty_or_invalid_ledger_is_not_anchored(tmp_path):
    with pytest.raises(audit_anchor.AuditAnchorError, match="no events"):
        audit_anchor.record_anchor(tmp_path / "empty.jsonl")
    _ledger(tmp_path)
    text = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    (tmp_path / "audit.jsonl").write_text(text.replace('"index": 1', '"index": 9'), encoding="utf-8")
    with pytest.raises(audit_anchor.AuditAnchorError, match="integrity"):
        audit_anchor.record_anchor(tmp_path / "audit.jsonl")


def test_a_rewritten_ledger_cannot_be_anchored_over(tmp_path):
    _ledger(tmp_path)
    audit_anchor.record_anchor(tmp_path / "audit.jsonl")
    _rebuild(tmp_path / "audit.jsonl", 3)
    with pytest.raises(audit_anchor.AuditAnchorError, match="rewritten"):
        audit_anchor.record_anchor(tmp_path / "audit.jsonl")


def test_malformed_anchors_fail_closed(tmp_path):
    _ledger(tmp_path)
    audit_anchor.record_anchor(tmp_path / "audit.jsonl")
    audit_anchor.anchors_path().write_text('{"schema": "audit-anchors/1", "anchors": [{"seq": true}]}', encoding="utf-8")
    with pytest.raises(audit_anchor.AuditAnchorError, match="malformed"):
        audit_anchor.anchor_problems(tmp_path / "audit.jsonl")


def _cli(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["skill-agents", *argv])
    code = 0
    try:
        cli.main()
    except SystemExit as exc:
        code = exc.code
    return code, capsys.readouterr().out


def test_cli_verify_audit_reports_a_broken_anchor_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    _ledger(tmp_path)
    audit = str(tmp_path / "audit.jsonl")
    code, out = _cli(monkeypatch, capsys, "anchor-audit", "--audit", audit)
    assert code == 0 and json.loads(out)["seq"] == 3
    assert _cli(monkeypatch, capsys, "verify-audit", "--audit", audit)[1].strip() == "VALID"
    _rebuild(tmp_path / "audit.jsonl", 3)
    code, out = _cli(monkeypatch, capsys, "verify-audit", "--audit", audit)
    assert code == 2 and out.startswith("INVALID")


def test_cli_checks_a_hash_kept_outside_the_machine(tmp_path, monkeypatch, capsys):
    """No stored anchor is involved, as when checking a restored copy against a note."""
    ledger = _ledger(tmp_path)
    audit = str(tmp_path / "audit.jsonl")
    event = ledger._events()[1]
    args = ("verify-audit", "--audit", audit, "--anchor-seq", "2", "--anchor-hash")
    assert _cli(monkeypatch, capsys, *args, event["event_hash"])[0] == 0
    assert _cli(monkeypatch, capsys, *args, "0" * 64)[0] == 2
    assert _cli(monkeypatch, capsys, "verify-audit", "--audit", audit, "--anchor-seq", "2")[0] != 0


def test_cli_add_and_list_approvers(tmp_path, monkeypatch, capsys):
    key_file = tmp_path / "key"
    key_file.write_bytes(KEY_A)
    code, out = _cli(monkeypatch, capsys, "add-approver", "--key-file", str(key_file), "--name", "owner")
    assert code == 0 and json.loads(out)["key_id"] == key_identifier(KEY_A)
    code, out = _cli(monkeypatch, capsys, "list-approvers")
    assert code == 0 and json.loads(out)[0]["name"] == "owner"
    code, _ = _cli(monkeypatch, capsys, "add-approver", "--key-file", str(key_file), "--name", " ")
    assert code not in (0, None)
