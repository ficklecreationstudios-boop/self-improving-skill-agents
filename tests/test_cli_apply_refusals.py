import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from self_improving_agents import revocation
from self_improving_agents.agents.review import propose_skill_update
from self_improving_agents.audit import AuditLedger
from self_improving_agents.cli import main
from self_improving_agents.governance.approval import Governance

KEY = b"test-only-approval-key-material-32-bytes-minimum!!"
OLD = "---\nid: demo\nname: Demo\ndomain: general\ntags: []\n---\nold body\n"
NEW = OLD.replace("old body", "new body")
SRC = Path(__file__).resolve().parents[1] / "src"


class Setup:
    def __init__(self, tmp_path, proposed=NEW):
        self.root = tmp_path
        self.target = tmp_path / "skills" / "demo" / "SKILL.md"
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(OLD.encode("utf-8"))
        self.ledger = AuditLedger(tmp_path / "audit.jsonl")
        self.archive = tmp_path / "archive"
        self.governance = Governance(tmp_path / "skills", self.archive, self.ledger, approval_key=KEY)
        self.proposal = propose_skill_update("demo", OLD, proposed, "refusal test")
        self.approval = self.governance.issue_approval(self.proposal, "me", True, "reviewed")
        self.key = tmp_path / "operator.approval-key"; self.key.write_bytes(KEY)
        self.proposal_file = tmp_path / "proposal.json"
        self.write_proposal({**self.proposal.payload(), "proposal_digest": self.proposal.proposal_digest})
        self.approval_file = tmp_path / "approval.json"
        self.write_approval(dict(self.approval.__dict__))
        self.audit = self.ledger.path

    def write_proposal(self, data):
        self.proposal_file.write_text(json.dumps(data), encoding="utf-8")

    def write_approval(self, data):
        self.approval_file.write_text(json.dumps(data), encoding="utf-8")

    def argv(self):
        return ["apply-proposal", str(self.proposal_file), str(self.approval_file), "--key-file", str(self.key),
                "--skills", str(self.root / "skills"), "--archive", str(self.archive), "--audit", str(self.audit)]

    def state(self):
        archived = sorted(p.name for p in self.archive.glob("*") if p.name != ".governance.lock") \
            if self.archive.exists() else []
        ledger = self.ledger.path.read_bytes() if self.ledger.path.exists() else None
        return self.target.read_bytes(), ledger, archived


def run_apply(monkeypatch, setup):
    monkeypatch.setattr(sys, "argv", ["skill-agents", *setup.argv()])
    with pytest.raises(SystemExit) as exit_info:
        main()
    message = exit_info.value.code
    assert isinstance(message, str), "a refusal must exit with a message (exit status 1)"
    assert "\n" not in message and "Traceback" not in message
    return message


def _stale(s):
    s.target.write_bytes((OLD + "edited after signing\n").encode("utf-8"))


def _revoked(s):
    s.governance.revoke_approval_key(s.approval.key_id, "rotation")


def _other_ledger(s):
    s.audit = s.root / "other-audit.jsonl"


def _registry_missing(s):
    revocation.registry_path().unlink()


def _bad_signature(s):
    s.write_approval({**s.approval.__dict__, "signature": "00" * 32})


def _different_proposal(s):
    other = propose_skill_update("demo", OLD, NEW.replace("new body", "other body"), "different")
    s.write_proposal({**other.payload(), "proposal_digest": other.proposal_digest})


def _tampered_proposal(s):
    s.write_proposal({**s.proposal.payload(), "proposed_content": NEW + "smuggled line\n",
                      "proposal_digest": s.proposal.proposal_digest})


def _corrupt_ledger(s):
    s.ledger.path.write_text("not-json\n", encoding="utf-8")


@pytest.mark.parametrize("damage, reason", [
    (_stale, "Stale proposal: base skill content has changed"),
    (_revoked, "Approval key is revoked"),
    (_other_ledger, "no matching approval-signed record"),
    (_registry_missing, "revocation registry is missing"),
    (_bad_signature, "Approval signature is missing or invalid"),
    (_different_proposal, "Approval does not bind this exact proposal"),
    (_tampered_proposal, "Proposal digest is invalid"),
    (_corrupt_ledger, "Audit ledger failed integrity verification"),
], ids=lambda value: value.__name__.strip("_") if callable(value) else "")
def test_governance_refusal_is_one_clean_line_and_changes_nothing(tmp_path, monkeypatch, damage, reason):
    setup = Setup(tmp_path)
    damage(setup)
    before = setup.state()
    message = run_apply(monkeypatch, setup)
    assert message.startswith("apply-proposal failed: ") and reason in message
    assert setup.state() == before


def test_unloadable_proposed_content_is_refused_cleanly(tmp_path, monkeypatch):
    setup = Setup(tmp_path, proposed="no frontmatter at all")
    before = setup.state()
    message = run_apply(monkeypatch, setup)
    assert message.startswith("apply-proposal failed: ") and "not a valid SKILL.md" in message
    assert setup.state() == before


def _write_raw(attribute, raw):
    def damage(s):
        getattr(s, attribute).write_bytes(raw)
    damage.__name__ = f"_{attribute}_raw"
    return damage


def _proposal_missing(s):
    s.proposal_file.unlink()


def _proposal_extra_field(s):
    s.write_proposal({**s.proposal.payload(), "proposal_digest": s.proposal.proposal_digest, "extra": "x"})


def _proposal_wrong_type(s):
    s.write_proposal({**s.proposal.payload(), "proposal_digest": s.proposal.proposal_digest, "rationale": 5})


def _approval_string_bool(s):
    s.write_approval({**s.approval.__dict__, "approved": "true"})


def _approval_null_approver(s):
    s.write_approval({**s.approval.__dict__, "approver": None})


def _key_missing(s):
    s.key.unlink()


def _key_too_short(s):
    s.key.write_bytes(b"short")


def _key_is_directory(s):
    s.key.unlink(); s.key.mkdir()


@pytest.mark.parametrize("damage, reason", [
    (_proposal_missing, "Cannot read proposal file"),
    (_write_raw("proposal_file", b"{not json"), "Cannot read proposal file"),
    (_write_raw("proposal_file", b"\xff\xfe\xfa not utf-8"), "Cannot read proposal file"),
    (_write_raw("proposal_file", b"[1, 2]"), "must be a JSON object with exactly the fields"),
    (_proposal_extra_field, "must be a JSON object with exactly the fields"),
    (_proposal_wrong_type, "fields of the wrong type: rationale"),
    (_write_raw("approval_file", b""), "Cannot read approval file"),
    (_approval_string_bool, "fields of the wrong type: approved"),
    (_approval_null_approver, "fields of the wrong type: approver"),
    (_key_missing, "Cannot use approval key"),
    (_key_too_short, "Cannot use approval key"),
    (_key_is_directory, "Cannot use approval key"),
], ids=lambda value: value.__name__.strip("_") if callable(value) else "")
def test_malformed_input_is_one_clean_line_and_changes_nothing(tmp_path, monkeypatch, damage, reason):
    setup = Setup(tmp_path)
    damage(setup)
    before = setup.state()
    message = run_apply(monkeypatch, setup)
    assert reason in message
    assert setup.state() == before


def test_unexpected_errors_keep_their_traceback(tmp_path, monkeypatch):
    setup = Setup(tmp_path)

    def broken(self, proposal, approval):
        raise ValueError("programming error, not a refusal")

    monkeypatch.setattr(Governance, "apply", broken)
    monkeypatch.setattr(sys, "argv", ["skill-agents", *setup.argv()])
    with pytest.raises(ValueError, match="programming error"):
        main()


def test_failure_after_commit_reports_recovery_instead_of_claiming_nothing_changed(tmp_path, monkeypatch):
    setup = Setup(tmp_path)
    real = Governance._write_journal

    def fail_final_journal(self, path, record):
        if record.get("phase") == "committed":
            raise OSError("injected journal failure")
        return real(self, path, record)

    monkeypatch.setattr(Governance, "_write_journal", fail_final_journal)
    message = run_apply(monkeypatch, setup)
    assert message.startswith("apply-proposal failed: ") and "needs recovery" in message
    assert setup.target.read_text(encoding="utf-8") == NEW


@pytest.mark.parametrize("damage, reason", [
    (_write_raw("proposal_file", b"{not json"), "Cannot read proposal file"),
    (_key_too_short, "Cannot use approval key"),
], ids=["proposal-not-json", "key-too-short"])
def test_real_process_exits_1_with_one_line_and_no_traceback(tmp_path, damage, reason):
    """Only refusals that stop before the revocation registry is read, so the real profile is never touched."""
    setup = Setup(tmp_path)
    damage(setup)
    before = setup.state()
    result = subprocess.run([sys.executable, "-m", "self_improving_agents.cli", *setup.argv()],
                            capture_output=True, text=True, timeout=60,
                            env={**os.environ, "PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1"})
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Traceback" not in result.stderr
    assert len(result.stderr.strip().splitlines()) == 1 and reason in result.stderr
    assert setup.state() == before
