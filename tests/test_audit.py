import json
from self_improving_agents.audit import AuditLedger

def test_audit_chain_validates_and_detects_tampering(tmp_path):
    path = tmp_path / "audit.jsonl"; ledger = AuditLedger(path)
    ledger.append("one", {"x": 1}); ledger.append("two", {"x": 2})
    assert ledger.verify()
    rows = path.read_text().splitlines(); row = json.loads(rows[0]); row["payload"]["x"] = 99
    rows[0] = json.dumps(row); path.write_text("\n".join(rows) + "\n")
    assert not ledger.verify()
