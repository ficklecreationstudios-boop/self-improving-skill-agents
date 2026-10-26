import json
import sys
from pathlib import Path

from self_improving_agents.agents.review import propose_skill_update
from self_improving_agents.cli import main


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
        "--approval-output", str(approval_path),
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
