from pathlib import Path

import json
import pytest

from self_improving_agents.agents.review import propose_skill_update
from self_improving_agents.audit import AuditLedger
from self_improving_agents.governance.approval import Governance, GovernanceError

KEY = b"test-only-approval-key-material-32-bytes-minimum!!"
OLD = "---\nid: demo\n---\nold content"
NEW = "---\nid: demo\n---\nnew content"


@pytest.mark.parametrize(
    "failure_point",
    ["target_write", "target_written_journal", "audit_append", "finalization_journal"],
)
def test_injected_transaction_failure_recovers_to_audited_state(tmp_path, monkeypatch, failure_point):
    root = tmp_path / "skills"
    folder = root / "demo"
    folder.mkdir(parents=True)
    target = folder / "SKILL.md"
    target.write_text(OLD, encoding="utf-8")
    archive = tmp_path / "archive"
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    governance = Governance(root, archive, ledger, approval_key=KEY)
    proposal = propose_skill_update("demo", OLD, NEW, "fault-injection recovery test")
    approval = governance.issue_approval(proposal, "test-reviewer", True, "approved test proposal")

    injected = False

    if failure_point == "target_write":
        original_atomic_write = governance._atomic_write

        def fail_target_write_once(path, content):
            nonlocal injected
            if Path(path).resolve() == target.resolve() and not injected:
                injected = True
                raise OSError("injected failure before target write")
            return original_atomic_write(path, content)

        monkeypatch.setattr(governance, "_atomic_write", fail_target_write_once)

    elif failure_point in {"target_written_journal", "finalization_journal"}:
        original_write_journal = governance._write_journal

        def fail_journal_once(path, record):
            nonlocal injected
            phase = record.get("phase")
            should_fail = (
                failure_point == "target_written_journal" and phase == "target_written"
            ) or (
                failure_point == "finalization_journal" and phase == "committed"
            )
            if should_fail and not injected:
                injected = True
                raise OSError(f"injected failure at journal phase {phase}")
            return original_write_journal(path, record)

        monkeypatch.setattr(governance, "_write_journal", fail_journal_once)

    elif failure_point == "audit_append":
        original_append = ledger.append

        def fail_commit_audit_once(event_type, payload):
            nonlocal injected
            if event_type == "skill_update_applied" and not injected:
                injected = True
                raise OSError("injected failure before commit audit")
            return original_append(event_type, payload)

        monkeypatch.setattr(ledger, "append", fail_commit_audit_once)

    if failure_point == "finalization_journal":
        with pytest.raises(GovernanceError, match="journal finalization needs recovery"):
            governance.apply(proposal, approval)
        assert injected
        assert target.read_text(encoding="utf-8") == NEW
        recovered = governance.recover_pending()
        assert recovered == ["finalized:demo"]
        assert target.read_text(encoding="utf-8") == NEW
    else:
        with pytest.raises(OSError, match="injected failure"):
            governance.apply(proposal, approval)
        assert injected
        assert target.read_text(encoding="utf-8") == OLD
        recovered = governance.recover_pending()
        assert recovered == ["rolled_back:demo"]
        assert target.read_text(encoding="utf-8") == OLD

    journals = list(archive.glob("*.txn.json"))
    assert len(journals) == 1
    record = json.loads(journals[0].read_text(encoding="utf-8"))
    assert record["phase"] in {"committed", "rolled_back"}
    assert ledger.verify()
