import json
from self_improving_agents.audit import AuditLedger
from self_improving_agents.agents.review import propose_skill_update
from self_improving_agents.governance.approval import Governance

KEY = b"test-only-approval-key-material-32-bytes-minimum!!"


def test_recovery_rolls_back_target_written_without_commit_audit(tmp_path):
    root = tmp_path / "skills"; folder = root / "demo"; folder.mkdir(parents=True)
    old = "---\nid: demo\n---\nold"
    new = "---\nid: demo\n---\nnew"
    target = folder / "SKILL.md"; target.write_text(new, encoding="utf-8")
    archive_root = tmp_path / "archive"; archive_root.mkdir()
    archive = archive_root / "demo.interrupted.SKILL.md"; archive.write_text(old, encoding="utf-8")
    journal = archive_root / "demo.interrupted.txn.json"
    journal.write_text(json.dumps({
        "schema": 1, "phase": "target_written", "skill_id": "demo",
        "target": str(target.resolve()), "archive": str(archive.resolve()),
        "old_digest": __import__("hashlib").sha256(old.encode()).hexdigest(),
        "new_digest": __import__("hashlib").sha256(new.encode()).hexdigest(),
        "proposal_digest": "a" * 64,
    }), encoding="utf-8")
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    gov = Governance(root, archive_root, ledger, approval_key=KEY)

    recovered = gov.recover_pending()
    assert recovered == ["rolled_back:demo"]
    assert target.read_text(encoding="utf-8") == old
    record = json.loads(journal.read_text(encoding="utf-8"))
    assert record["phase"] == "rolled_back"
    assert ledger.verify()
    assert any(json.loads(line)["type"] == "skill_update_recovered_rollback"
               for line in ledger.path.read_text(encoding="utf-8").splitlines())


def test_recovery_finalizes_audited_transaction(tmp_path):
    root = tmp_path / "skills"; folder = root / "demo"; folder.mkdir(parents=True)
    old = "---\nid: demo\n---\nold"
    new = "---\nid: demo\n---\nnew"
    target = folder / "SKILL.md"; target.write_text(new, encoding="utf-8")
    archive_root = tmp_path / "archive"; archive_root.mkdir()
    archive = archive_root / "demo.interrupted.SKILL.md"; archive.write_text(old, encoding="utf-8")
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    proposal = propose_skill_update("demo", old, new, "test")
    ledger.append("skill_update_applied", {"proposal_digest": proposal.proposal_digest,
                  "new_digest": __import__("hashlib").sha256(new.encode()).hexdigest()})
    journal = archive_root / "demo.interrupted.txn.json"
    journal.write_text(json.dumps({
        "schema": 1, "phase": "target_written", "skill_id": "demo",
        "target": str(target.resolve()), "archive": str(archive.resolve()),
        "old_digest": __import__("hashlib").sha256(old.encode()).hexdigest(),
        "new_digest": __import__("hashlib").sha256(new.encode()).hexdigest(),
        "proposal_digest": proposal.proposal_digest,
    }), encoding="utf-8")
    gov = Governance(root, archive_root, ledger, approval_key=KEY)

    recovered = gov.recover_pending()
    assert recovered == ["finalized:demo"]
    assert target.read_text(encoding="utf-8") == new
    assert json.loads(journal.read_text(encoding="utf-8"))["phase"] == "committed"
