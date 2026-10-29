"""F4: recovery of a torn final audit line, preserving evidence and refusing ambiguity."""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from self_improving_agents.audit import AuditIntegrityError, AuditLedger


def _ledger(tmp_path):
    path = tmp_path / "audit.jsonl"
    ledger = AuditLedger(path)
    ledger.append("first", {"n": 1})
    ledger.append("second", {"n": 2})
    ledger.append("third", {"n": 3, "note": "multi-byte € to tear mid-character"})
    return path, ledger


def _types(ledger):
    return [event["type"] for event in ledger._events()]


def _quarantines(path):
    return sorted(path.parent.glob(path.name + ".torn-*.bak"))


def test_clean_ledger_is_left_untouched(tmp_path):
    path, ledger = _ledger(tmp_path)
    before = path.read_bytes()

    assert ledger.recover_torn_tail()["status"] == "clean"
    assert path.read_bytes() == before
    assert _quarantines(path) == []


def test_truncation_at_every_byte_of_final_record_is_recovered(tmp_path):
    source, _ = _ledger(tmp_path / "source")
    full = source.read_bytes()
    final_start = full.rstrip(b"\n").rfind(b"\n") + 1
    final_line = full[final_start:]
    for keep in range(1, len(final_line) - 1):  # every partial record; len-1 is C2 (only "\n" lost)
        case = tmp_path / f"cut-{keep}"
        case.mkdir()
        path = case / "audit.jsonl"
        torn = full[:final_start + keep]
        path.write_bytes(torn)
        ledger = AuditLedger(path)
        assert ledger.verify() is False, keep

        result = ledger.recover_torn_tail()

        assert result["status"] == "recovered" and result["action"] == "audit_tail_truncated", (keep, result)
        assert result["removed_bytes"] == keep
        assert ledger.verify() is True
        assert _types(ledger) == ["first", "second", "audit_tail_truncated"]
        payload = ledger._events()[-1]["payload"]
        assert payload["removed_sha256"] == hashlib.sha256(torn[final_start:]).hexdigest()
        assert payload["original_sha256"] == hashlib.sha256(torn).hexdigest()
        (quarantine,) = _quarantines(path)
        assert quarantine.read_bytes() == torn
        ledger.append("after_recovery", {})
        assert ledger.verify() is True


def test_complete_record_missing_only_newline_is_kept(tmp_path):
    path, ledger = _ledger(tmp_path)
    original_events = ledger._events()
    path.write_bytes(path.read_bytes()[:-1])
    assert ledger.verify() is False  # otherwise the next append would merge two records
    with pytest.raises(AuditIntegrityError):
        ledger.append("must_not_merge", {})

    result = ledger.recover_torn_tail()

    assert result["status"] == "recovered" and result["action"] == "audit_tail_completed"
    assert result["removed_bytes"] == 0
    events = ledger._events()
    assert events[:3] == original_events
    assert events[3]["type"] == "audit_tail_completed"
    assert ledger.verify() is True


@pytest.mark.parametrize("tail", [b"\x00" * 64, b'{"seq": 4, "type": "x", "pay\xe2\x82', b"   ", b"[1, 2]", b"{}"],
                         ids=["nul-filled", "invalid-utf8", "whitespace", "non-object", "object-off-chain"])
def test_garbage_tail_is_truncated_and_preserved(tmp_path, tail):
    path, ledger = _ledger(tmp_path)
    torn = path.read_bytes() + tail
    path.write_bytes(torn)

    result = ledger.recover_torn_tail()

    assert result["status"] == "recovered" and result["action"] == "audit_tail_truncated"
    assert result["removed_bytes"] == len(tail)
    assert _types(ledger) == ["first", "second", "third", "audit_tail_truncated"]
    assert _quarantines(path)[0].read_bytes() == torn


@pytest.mark.parametrize("position", ["middle", "final"])
def test_malformed_complete_line_is_refused_without_changes(tmp_path, position):
    path, ledger = _ledger(tmp_path)
    lines = path.read_bytes().splitlines(keepends=True)
    index = 1 if position == "middle" else 2
    lines[index] = b'{"not": "a valid event"}\n'
    damaged = b"".join(lines) + b'{"partial'
    path.write_bytes(damaged)

    result = ledger.recover_torn_tail()

    assert result["status"] == "refused"
    assert path.read_bytes() == damaged
    assert _quarantines(path) == []


def test_tampered_prefix_with_torn_tail_is_refused(tmp_path):
    path, ledger = _ledger(tmp_path)
    lines = path.read_bytes().splitlines(keepends=True)
    event = json.loads(lines[0]); event["payload"]["n"] = 99
    damaged = (json.dumps(event, sort_keys=True) + "\n").encode() + b"".join(lines[1:]) + b'{"seq": 4'
    path.write_bytes(damaged)

    assert ledger.recover_torn_tail()["status"] == "refused"
    assert path.read_bytes() == damaged
    assert _quarantines(path) == []


def test_recovery_is_idempotent(tmp_path):
    path, ledger = _ledger(tmp_path)
    path.write_bytes(path.read_bytes() + b'{"seq": 4, "ty')
    assert ledger.recover_torn_tail()["status"] == "recovered"
    after_first = path.read_bytes()

    assert ledger.recover_torn_tail()["status"] == "clean"
    assert path.read_bytes() == after_first
    assert len(_quarantines(path)) == 1


def test_append_still_refuses_a_torn_ledger_before_recovery(tmp_path):
    path, ledger = _ledger(tmp_path)
    path.write_bytes(path.read_bytes() + b'{"seq": 4')

    with pytest.raises(AuditIntegrityError):
        ledger.append("must_not_append", {})


def test_crash_before_replace_leaves_original_and_retry_converges(tmp_path, monkeypatch):
    path, ledger = _ledger(tmp_path)
    torn = path.read_bytes() + b'{"seq": 4, "type": "fo'
    path.write_bytes(torn)
    real_replace = os.replace

    def crash_on_ledger_replace(source, target):
        if Path(target) == path:
            raise OSError("simulated crash before replace")
        real_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", crash_on_ledger_replace)
        with pytest.raises(OSError, match="simulated crash"):
            ledger.recover_torn_tail()
    assert path.read_bytes() == torn
    assert not (tmp_path / "audit.jsonl.recover.tmp").exists()
    assert len(_quarantines(path)) == 1

    assert ledger.recover_torn_tail()["status"] == "recovered"
    assert len(_quarantines(path)) == 1 and _quarantines(path)[0].read_bytes() == torn
    assert ledger.verify() is True


def test_failure_to_write_backup_refuses_without_changes(tmp_path, monkeypatch):
    path, ledger = _ledger(tmp_path)
    torn = path.read_bytes() + b'{"seq": 4'
    path.write_bytes(torn)

    def fail(*_args, **_kwargs):
        raise OSError("simulated failure while writing the backup")

    monkeypatch.setattr(AuditLedger, "_durable_write", classmethod(fail))
    result = ledger.recover_torn_tail()

    assert result["status"] == "refused" and "could not preserve" in result["reason"]
    assert path.read_bytes() == torn
    assert _quarantines(path) == [] and list(tmp_path.glob("*.partial")) == []


def test_backup_that_does_not_match_original_refuses_without_changes(tmp_path, monkeypatch):
    path, ledger = _ledger(tmp_path)
    torn = path.read_bytes() + b'{"seq": 4'
    path.write_bytes(torn)
    original_write = AuditLedger._durable_write.__func__

    def corrupting_write(cls, target, data):
        if target.name.endswith(".partial"):
            data = data[:-1] + b"X"  # simulate a silently corrupted backup copy
        return original_write(cls, target, data)

    monkeypatch.setattr(AuditLedger, "_durable_write", classmethod(corrupting_write))
    result = ledger.recover_torn_tail()

    assert result["status"] == "refused" and "does not match" in result["reason"]
    assert path.read_bytes() == torn
    assert _quarantines(path) == [] and list(tmp_path.glob("*.partial")) == []


def test_crash_after_replace_leaves_recovered_ledger(tmp_path, monkeypatch):
    path, ledger = _ledger(tmp_path)
    path.write_bytes(path.read_bytes() + b'{"seq": 4')
    real_replace, replaced = os.replace, []

    def replace_then_note(source, target):
        real_replace(source, target)
        if Path(target) == path:
            replaced.append(target)

    def crash_once_replaced(_path):
        if replaced:
            raise RuntimeError("simulated crash after replace")

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", replace_then_note)
        patch.setattr(AuditLedger, "_fsync_directory", staticmethod(crash_once_replaced))
        with pytest.raises(RuntimeError, match="simulated crash"):
            ledger.recover_torn_tail()
    assert ledger.verify() is True
    assert _types(ledger)[-1] == "audit_tail_truncated"
    assert ledger.recover_torn_tail()["status"] == "clean"


def test_concurrent_append_waits_for_recovery_and_chains_after_it(tmp_path, monkeypatch):
    path, ledger = _ledger(tmp_path)
    path.write_bytes(path.read_bytes() + b'{"seq": 4')
    original_write = AuditLedger._durable_write.__func__
    in_recovery, release = threading.Event(), threading.Event()

    def slow_write(cls, target, data):
        if target.name.endswith(".recover.tmp"):
            in_recovery.set()
            release.wait(5)
        return original_write(cls, target, data)

    monkeypatch.setattr(AuditLedger, "_durable_write", classmethod(slow_write))
    results = {}
    recovery = threading.Thread(target=lambda: results.setdefault("recovery", ledger.recover_torn_tail()))
    recovery.start()
    assert in_recovery.wait(5)
    writer = threading.Thread(target=lambda: results.setdefault("append", AuditLedger(path).append("concurrent", {})))
    writer.start()
    time.sleep(0.3)
    assert "append" not in results  # blocked on the ledger lock while recovery holds it
    release.set()
    recovery.join(15); writer.join(15)

    assert results["recovery"]["status"] == "recovered"
    assert _types(ledger) == ["first", "second", "third", "audit_tail_truncated", "concurrent"]
    assert ledger.verify() is True


def test_cli_recover_audit_reports_status_and_exit_code(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    torn, _ = _ledger(tmp_path / "torn")
    torn.write_bytes(torn.read_bytes() + b'{"seq": 4')
    refused, _ = _ledger(tmp_path / "refused")
    refused.write_bytes(b'{"not": "valid"}\n' + b'{"partial')

    ok = subprocess.run([sys.executable, "-m", "self_improving_agents.cli", "recover-audit", "--audit", str(torn)],
                        capture_output=True, text=True, env=env, check=False)
    bad = subprocess.run([sys.executable, "-m", "self_improving_agents.cli", "recover-audit", "--audit", str(refused)],
                         capture_output=True, text=True, env=env, check=False)

    assert ok.returncode == 0 and json.loads(ok.stdout)["status"] == "recovered", ok.stderr
    assert bad.returncode == 2 and json.loads(bad.stdout)["status"] == "refused", bad.stderr
