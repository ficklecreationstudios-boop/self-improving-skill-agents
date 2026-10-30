import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from self_improving_agents import cli
from self_improving_agents.agents.review import propose_skill_update
from self_improving_agents.cli import main


def test_init_approval_key_is_accessible_only_to_the_current_user(tmp_path, monkeypatch):
    key_path = tmp_path / "keys" / "operator.approval-key"
    monkeypatch.setattr(sys, "argv", ["skill-agents", "init-approval-key", str(key_path)])
    main()
    assert len(key_path.read_bytes()) == 32
    if os.name != "nt":
        assert key_path.stat().st_mode & 0o777 == 0o600
        return
    listing = subprocess.run(["icacls", str(key_path)], capture_output=True, text=True, check=True).stdout
    aces = [line.replace(str(key_path), "").strip() for line in listing.split("\n\n")[0].splitlines() if line.strip()]
    me = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip()
    assert [ace.casefold() for ace in aces] == [f"{me}:(F)".casefold()], listing


def test_init_approval_key_fails_closed_when_access_cannot_be_restricted(tmp_path, monkeypatch):
    def refuse(path):
        raise RuntimeError("simulated ACL failure")

    key_path = tmp_path / "operator.approval-key"
    monkeypatch.setattr(cli, "restrict_to_current_user", refuse)
    monkeypatch.setattr(sys, "argv", ["skill-agents", "init-approval-key", str(key_path)])
    with pytest.raises(SystemExit, match="no key was created"):
        main()
    assert not key_path.exists()


def test_cli_signed_approval_lifecycle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skill_dir = tmp_path / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    old = "---\nid: demo\nname: Demo\ndomain: general\ntags: []\n---\nUse clear steps."
    new = "---\nid: demo\nname: Demo\ndomain: general\ntags: []\n---\nUse clear steps and state uncertainty."
    target = skill_dir / "SKILL.md"
    target.write_text(old, encoding="utf-8")
    proposal = propose_skill_update("demo", old, new, "feedback and regression review")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps({**proposal.payload(), "proposal_digest": proposal.proposal_digest}), encoding="utf-8")
    key_path = tmp_path / "outside" / "operator.approval-key"
    approval_path = tmp_path / "approval.json"

    monkeypatch.setattr(sys, "argv", ["skill-agents", "init-approval-key", str(key_path)])
    main()
    assert key_path.exists() and len(key_path.read_bytes()) == 32

    monkeypatch.setattr("builtins.input", lambda prompt="": "demo")
    monkeypatch.setattr(sys, "argv", [
        "skill-agents", "approve-proposal", str(proposal_path), "--key-file", str(key_path),
        "--approver", "test-reviewer", "--reason", "reviewed", "--approve",
        "--approval-output", str(approval_path), "--audit", str(tmp_path / "audit.jsonl"),
    ])
    main()
    assert json.loads(approval_path.read_text(encoding="utf-8"))["signature"]

    monkeypatch.setattr(sys, "argv", [
        "skill-agents", "apply-proposal", str(proposal_path), str(approval_path),
        "--key-file", str(key_path), "--skills", str(tmp_path / "skills"),
        "--archive", str(tmp_path / "archive"), "--audit", str(tmp_path / "audit.jsonl"),
    ])
    main()
    assert target.read_text(encoding="utf-8") == new


def test_propose_refuses_content_that_is_not_a_valid_skill(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skills" / "demo"; skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nid: demo\n---\nold", encoding="utf-8")
    (tmp_path / "proposed.md").write_text("no frontmatter at all", encoding="utf-8")
    output = tmp_path / "proposal.json"
    monkeypatch.setattr(sys, "argv", ["skill-agents", "propose", "demo", str(tmp_path / "proposed.md"),
                                      "--rationale", "r", "--skills", str(tmp_path / "skills"), "--output", str(output)])
    with pytest.raises(SystemExit, match="not a valid SKILL.md"):
        main()
    assert not output.exists()


OLD_SKILL = "---\nid: demo\nname: Demo\ndomain: general\ntags: []\n---\nold body\n"
NEW_SKILL = OLD_SKILL.replace("old body", "new body")
TEST_KEY = b"test-only-approval-key-material-32-bytes-minimum!!"


def review_setup(tmp_path, proposed=NEW_SKILL):
    skill_dir = tmp_path / "skills" / "demo"; skill_dir.mkdir(parents=True)
    target = skill_dir / "SKILL.md"; target.write_bytes(OLD_SKILL.encode("utf-8"))
    proposal = propose_skill_update("demo", OLD_SKILL, proposed, "feedback said the body was wrong")
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps({**proposal.payload(), "proposal_digest": proposal.proposal_digest}),
                             encoding="utf-8")
    key_path = tmp_path / "operator.approval-key"; key_path.write_bytes(TEST_KEY)
    argv = ["skill-agents", "approve-proposal", str(proposal_path), "--key-file", str(key_path),
            "--approver", "me", "--reason", "reviewed", "--approve",
            "--approval-output", str(tmp_path / "approval.json"), "--audit", str(tmp_path / "audit.jsonl"),
            "--skills", str(tmp_path / "skills"), "--archive", str(tmp_path / "archive")]
    return target, argv


def signed_records(tmp_path):
    ledger = tmp_path / "audit.jsonl"
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["type"] == "proposal_approval_signed"]


def test_approve_shows_current_and_proposed_skill_before_asking_for_confirmation(tmp_path, monkeypatch, capsys):
    _, argv = review_setup(tmp_path)
    shown = {}

    def confirm(prompt=""):
        shown["before_prompt"] = capsys.readouterr().out
        shown["prompt"] = prompt
        assert not (tmp_path / "approval.json").exists() and not signed_records(tmp_path)
        return "demo"

    monkeypatch.setattr("builtins.input", confirm)
    monkeypatch.setattr(sys, "argv", argv)
    main()
    out = shown["before_prompt"]
    order = [out.index(marker) for marker in ("CURRENT SKILL", "old body", "PROPOSED REPLACEMENT", "new body",
                                              "CHANGES (current -> proposed)", "-old body", "+new body")]
    assert order == sorted(order)
    assert "feedback said the body was wrong" in out
    assert "'demo'" in shown["prompt"]
    assert json.loads((tmp_path / "approval.json").read_text(encoding="utf-8"))["signature"]
    assert len(signed_records(tmp_path)) == 1


@pytest.mark.parametrize("typed", ["", "Demo", " demo", "demo ", "other", None],
                         ids=["empty", "wrong-case", "leading-space", "trailing-space", "other-id", "no-input"])
def test_approve_signs_nothing_without_the_exact_skill_id(tmp_path, monkeypatch, typed):
    target, argv = review_setup(tmp_path)

    def confirm(prompt=""):
        if typed is None:
            raise EOFError
        return typed

    monkeypatch.setattr("builtins.input", confirm)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit, match="nothing was signed"):
        main()
    assert not (tmp_path / "approval.json").exists()
    assert signed_records(tmp_path) == []
    assert target.read_text(encoding="utf-8") == OLD_SKILL


def _never_asked(prompt=""):
    raise AssertionError("confirmation must not be requested")


def test_approve_refuses_a_stale_proposal_before_review(tmp_path, monkeypatch, capsys):
    target, argv = review_setup(tmp_path)
    target.write_text(OLD_SKILL + "edited after the proposal\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", _never_asked)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit, match="Stale proposal.*nothing was signed"):
        main()
    assert "PROPOSED REPLACEMENT" not in capsys.readouterr().out
    assert not (tmp_path / "approval.json").exists() and signed_records(tmp_path) == []


def test_approve_refuses_if_the_skill_changes_during_review(tmp_path, monkeypatch):
    target, argv = review_setup(tmp_path)

    def confirm_after_concurrent_edit(prompt=""):
        target.write_text(OLD_SKILL + "edited while the reviewer was reading\n", encoding="utf-8")
        return "demo"

    monkeypatch.setattr("builtins.input", confirm_after_concurrent_edit)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit, match="Stale proposal.*nothing was signed"):
        main()
    assert not (tmp_path / "approval.json").exists() and signed_records(tmp_path) == []


def test_approve_refuses_a_revoked_key_before_review(tmp_path, monkeypatch, capsys):
    _, argv = review_setup(tmp_path)
    from self_improving_agents.approval_auth import key_identifier
    from self_improving_agents.audit import AuditLedger
    from self_improving_agents.governance.approval import Governance
    Governance(tmp_path / "skills", tmp_path / "archive", AuditLedger(tmp_path / "audit.jsonl")
               ).revoke_approval_key(key_identifier(TEST_KEY), "rotation")
    monkeypatch.setattr("builtins.input", _never_asked)
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit, match="revoked.*nothing was signed"):
        main()
    assert "CURRENT SKILL" not in capsys.readouterr().out
    assert not (tmp_path / "approval.json").exists()


def test_review_shows_hidden_control_and_formatting_characters_visibly(tmp_path, monkeypatch, capsys):
    hidden = NEW_SKILL.replace("new body", "new body\x1b[2K\x1b[1A\rlooks harmless \u202egnp.exe\u200b")
    _, argv = review_setup(tmp_path, proposed=hidden)
    monkeypatch.setattr("builtins.input", lambda prompt="": "cancel")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit, match="nothing was signed"):
        main()
    out = capsys.readouterr().out
    for escaped in (r"\u001b[2K", r"\u001b[1A", r"\u000d", r"\u202e", r"\u200b"):
        assert escaped in out
    assert not any(char in out for char in "\x1b\r\u202e\u200b")
