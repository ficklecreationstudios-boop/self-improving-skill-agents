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
