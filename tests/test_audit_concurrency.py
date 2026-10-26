from concurrent.futures import ThreadPoolExecutor
import json
from self_improving_agents.audit import AuditLedger


def _append_many(path, worker, count):
    ledger = AuditLedger(path)
    for index in range(count):
        ledger.append("concurrent_test", {"worker": worker, "index": index})


def test_concurrent_writers_preserve_sequence_and_hash_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    workers = 8
    per_worker = 12
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_append_many, path, worker, per_worker) for worker in range(workers)]
        for future in futures:
            future.result(timeout=30)

    ledger = AuditLedger(path)
    assert ledger.verify()
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(events) == workers * per_worker
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert len({event["event_hash"] for event in events}) == len(events)


def test_empty_audit_is_valid_and_append_is_durable_shape(tmp_path):
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    assert ledger.verify()
    event = ledger.append("first", {"durable": True})
    assert event["seq"] == 1
    assert ledger.verify()
