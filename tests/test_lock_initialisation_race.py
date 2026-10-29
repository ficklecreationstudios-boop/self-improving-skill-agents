"""Finding F2: Windows lock files must not be written before the byte-range lock is held.

Reproduces the interleaving deterministically: another handle already holds the lock on
byte 0 of an empty lock file. Entering the lock must wait for that holder, not fail with
PermissionError while writing an initialisation byte into the locked region.
"""
import os
import threading
import time

import pytest

from self_improving_agents.audit import AuditLedger
from self_improving_agents.governance.approval import Governance

pytestmark = pytest.mark.skipif(os.name != "nt", reason="msvcrt byte-range locking is Windows-only")

HOLD_SECONDS = 0.5


def _hold_then_release(lock_path, held, released):
    import msvcrt

    with open(lock_path, "a+b") as holder:
        holder.seek(0)
        msvcrt.locking(holder.fileno(), msvcrt.LK_NBLCK, 1)
        held.set()
        time.sleep(HOLD_SECONDS)
        holder.seek(0)
        msvcrt.locking(holder.fileno(), msvcrt.LK_UNLCK, 1)
        released.set()


def _enter_while_empty_file_is_held(lock_path, enter_lock):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_bytes(b"")
    held, released = threading.Event(), threading.Event()
    holder = threading.Thread(target=_hold_then_release, args=(lock_path, held, released))
    holder.start()
    try:
        assert held.wait(5), "holder thread could not lock byte 0 of the empty lock file"
        started = time.monotonic()
        with enter_lock():
            waited = time.monotonic() - started
            entered_after_release = released.is_set()
    finally:
        holder.join(10)
    return waited, entered_after_release


def test_governance_lock_waits_for_holder_of_empty_lock_file(tmp_path):
    governance = Governance(tmp_path / "skills", tmp_path / "archive", AuditLedger(tmp_path / "audit.jsonl"))

    waited, entered_after_release = _enter_while_empty_file_is_held(
        governance.lock_path, governance._update_lock)

    assert entered_after_release
    assert waited >= HOLD_SECONDS * 0.8, waited


def test_audit_lock_waits_for_holder_of_empty_lock_file(tmp_path):
    ledger = AuditLedger(tmp_path / "audit.jsonl")

    waited, entered_after_release = _enter_while_empty_file_is_held(
        ledger.lock_path, ledger._exclusive_lock)

    assert entered_after_release
    assert waited >= HOLD_SECONDS * 0.8, waited
