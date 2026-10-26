import json
import multiprocessing
from pathlib import Path

from self_improving_agents.audit import AuditLedger


def _append_events(path: str, worker: int, count: int) -> None:
    ledger = AuditLedger(path)
    for index in range(count):
        ledger.append("concurrent_writer_probe", {"worker": worker, "index": index})


def test_audit_ledger_serializes_independent_process_writers(tmp_path):
    path = str(tmp_path / "multiprocess-audit.jsonl")
    worker_count = 4
    events_per_worker = 12
    workers = [
        multiprocessing.Process(target=_append_events, args=(path, worker, events_per_worker))
        for worker in range(worker_count)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)
    for worker in workers:
        assert not worker.is_alive(), "audit writer process hung"
        assert worker.exitcode == 0

    ledger = AuditLedger(path)
    assert ledger.verify()
    events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
    assert len(events) == worker_count * events_per_worker
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    observed = {(event["payload"]["worker"], event["payload"]["index"]) for event in events}
    expected = {
        (worker, index)
        for worker in range(worker_count)
        for index in range(events_per_worker)
    }
    assert observed == expected
