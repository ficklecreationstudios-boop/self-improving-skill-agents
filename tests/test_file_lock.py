import ctypes
import gc
import json
import os
import subprocess
import sys
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from self_improving_agents import file_lock
from self_improving_agents.agents.review import propose_skill_update
from self_improving_agents.approval_auth import key_identifier
from self_improving_agents.audit import AuditLedger
from self_improving_agents.file_lock import LockTimeoutError, exclusive_lock
from self_improving_agents.governance.approval import Governance, GovernanceError
from self_improving_agents import revocation

windows_only = pytest.mark.skipif(os.name != "nt", reason="LockFileEx and msvcrt locks are Windows-only")
SRC = Path(__file__).resolve().parents[1] / "src"
KEY = b"test-only-approval-key-material-32-bytes-minimum!!"


def hold_in_thread(path, seconds):
    """Hold the lock in another thread; returns (held, released_at) once it is held."""
    held, released_at = threading.Event(), []

    def run():
        with exclusive_lock(path):
            held.set()
            time.sleep(seconds)
            released_at.append(time.monotonic())

    thread = threading.Thread(target=run)
    thread.start()
    assert held.wait(5)
    return thread, released_at


def test_waiter_is_woken_promptly_when_the_holder_releases(tmp_path):
    lock = tmp_path / "x.lock"
    thread, released_at = hold_in_thread(lock, 0.5)
    with exclusive_lock(lock):
        acquired_at = time.monotonic()
    thread.join()
    assert acquired_at - released_at[0] < 0.25, "waiter must not sleep in one-second steps"


def test_timeout_fails_closed_and_leaves_nothing_held(tmp_path):
    lock = tmp_path / "x.lock"
    thread, _ = hold_in_thread(lock, 1.5)
    started = time.monotonic()
    with pytest.raises(LockTimeoutError) as error:
        with exclusive_lock(lock, timeout=0.4):
            pytest.fail("body must not run without the lock")
    assert isinstance(error.value, OSError)
    assert 0.35 <= time.monotonic() - started < 1.4
    thread.join()
    started = time.monotonic()
    with exclusive_lock(lock, timeout=1):
        assert time.monotonic() - started < 0.25


def test_audit_append_that_cannot_get_the_lock_fails_closed(tmp_path, monkeypatch):
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    ledger.append("before", {})
    before = ledger.path.read_bytes()
    monkeypatch.setattr(file_lock, "LOCK_TIMEOUT_SECONDS", 0.4)
    thread, _ = hold_in_thread(ledger.lock_path, 1.2)
    with pytest.raises(LockTimeoutError):
        ledger.append("blocked", {})
    thread.join()
    assert ledger.path.read_bytes() == before and ledger.verify()


@windows_only
def test_interrupted_wait_cancels_the_request(tmp_path, monkeypatch):
    lock = tmp_path / "x.lock"
    thread, _ = hold_in_thread(lock, 0.6)

    def interrupt(event, milliseconds):
        raise KeyboardInterrupt

    with monkeypatch.context() as patched:
        patched.setattr(file_lock, "_wait", interrupt)
        with pytest.raises(KeyboardInterrupt):
            with exclusive_lock(lock):
                pytest.fail("body must not run")
    thread.join()
    started = time.monotonic()
    with exclusive_lock(lock, timeout=1):
        assert time.monotonic() - started < 0.25, "a cancelled request must not keep the lock"


@windows_only
def test_interruption_racing_a_grant_gives_the_lock_back(tmp_path, monkeypatch):
    lock = tmp_path / "x.lock"
    release = threading.Event()
    held = threading.Event()

    def holder():
        with exclusive_lock(lock):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder); thread.start()
    assert held.wait(5)
    real_wait = file_lock._wait

    def grant_then_interrupt(event, milliseconds):
        release.set()
        thread.join(5)
        real_wait(event, 2000)  # the pending request is granted here
        raise KeyboardInterrupt

    with monkeypatch.context() as patched:
        patched.setattr(file_lock, "_wait", grant_then_interrupt)
        with pytest.raises(KeyboardInterrupt):
            with exclusive_lock(lock):
                pytest.fail("body must not run")
    started = time.monotonic()
    with exclusive_lock(lock, timeout=1):
        assert time.monotonic() - started < 0.25, "a lock granted during interruption must be given back"


HOLDER = """
import sys, time
sys.path.insert(0, sys.argv[1])
from self_improving_agents.file_lock import exclusive_lock
with exclusive_lock(sys.argv[2], timeout=float(sys.argv[4])):
    open(sys.argv[3], "w").close()
    time.sleep(60)
"""


def spawn_holder(lock, marker, timeout=30):
    return subprocess.Popen([sys.executable, "-c", HOLDER, str(SRC), str(lock), str(marker), str(timeout)])


def wait_for(path, seconds=15):
    deadline = time.monotonic() + seconds
    while not path.exists():
        assert time.monotonic() < deadline, f"{path.name} never appeared"
        time.sleep(0.02)


def test_killed_holder_process_releases_the_lock(tmp_path):
    lock, marker = tmp_path / "x.lock", tmp_path / "held"
    process = spawn_holder(lock, marker)
    try:
        wait_for(marker)
        with pytest.raises(LockTimeoutError):
            with exclusive_lock(lock, timeout=0.3):
                pass
        process.kill(); process.wait(10)
        started = time.monotonic()
        with exclusive_lock(lock, timeout=5):
            assert time.monotonic() - started < 2
    finally:
        process.kill()


def test_killed_waiting_process_leaves_no_lock_behind(tmp_path):
    lock, marker = tmp_path / "x.lock", tmp_path / "never"
    release = threading.Event()
    held = threading.Event()

    def holder():
        with exclusive_lock(lock):
            held.set()
            release.wait(10)

    thread = threading.Thread(target=holder); thread.start()
    assert held.wait(5)
    waiter = spawn_holder(lock, marker)
    try:
        time.sleep(1.0)  # the waiter is now blocked in its lock request
        assert waiter.poll() is None and not marker.exists()
        waiter.kill(); waiter.wait(10)
    finally:
        release.set(); thread.join(10); waiter.kill()
    started = time.monotonic()
    with exclusive_lock(lock, timeout=2):
        assert time.monotonic() - started < 0.5
    assert not marker.exists()


@windows_only
def test_excludes_and_is_excluded_by_msvcrt_locking_on_the_same_byte(tmp_path):
    import msvcrt
    lock = tmp_path / "x.lock"
    with open(lock, "a+b") as legacy:
        legacy.seek(0)
        msvcrt.locking(legacy.fileno(), msvcrt.LK_NBLCK, 1)
        with pytest.raises(LockTimeoutError):
            with exclusive_lock(lock, timeout=0.3):
                pass
        legacy.seek(0)
        msvcrt.locking(legacy.fileno(), msvcrt.LK_UNLCK, 1)
    with exclusive_lock(lock):
        with open(lock, "a+b") as legacy:
            legacy.seek(0)
            with pytest.raises(OSError):
                msvcrt.locking(legacy.fileno(), msvcrt.LK_NBLCK, 1)


def test_the_locked_byte_is_never_written(tmp_path):
    lock = tmp_path / "x.lock"
    for _ in range(3):
        with exclusive_lock(lock):
            pass
    assert lock.stat().st_size == 0


def _append_many(path, worker, count):
    ledger = AuditLedger(path)
    for index in range(count):
        ledger.append("concurrency", {"worker": worker, "index": index})


def assert_complete_chain(path, writers, per_writer):
    ledger = AuditLedger(path)
    assert ledger.verify()
    events = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]
    assert [event["seq"] for event in events] == list(range(1, writers * per_writer + 1))
    assert {(e["payload"]["worker"], e["payload"]["index"]) for e in events} == \
        {(w, i) for w in range(writers) for i in range(per_writer)}


@pytest.mark.parametrize("writers", [2, 4, 8, 10, 12, 16, 24, 32])
def test_simultaneous_thread_writers_all_succeed(tmp_path, writers):
    path = tmp_path / "audit.jsonl"
    with ThreadPoolExecutor(max_workers=writers) as pool:
        for future in [pool.submit(_append_many, path, w, 12) for w in range(writers)]:
            future.result(timeout=120)
    assert_complete_chain(path, writers, 12)


WRITER = """
import sys, time
sys.path.insert(0, sys.argv[1])
from self_improving_agents.audit import AuditLedger
start_at = float(sys.argv[4])
while time.time() < start_at:
    time.sleep(0.005)
ledger = AuditLedger(sys.argv[2])
for index in range(12):
    ledger.append("concurrency", {"worker": int(sys.argv[3]), "index": index})
"""


@pytest.mark.parametrize("writers", [12, 24])
def test_simultaneous_process_writers_all_succeed(tmp_path, writers):
    path = tmp_path / "audit.jsonl"
    start_at = time.time() + 3
    processes = [subprocess.Popen([sys.executable, "-c", WRITER, str(SRC), str(path), str(w), repr(start_at)],
                                  stderr=subprocess.PIPE, text=True) for w in range(writers)]
    errors = []
    for process in processes:
        _, stderr = process.communicate(timeout=180)
        if process.returncode != 0:
            errors.append(stderr[-300:])
    assert not errors, errors
    assert_complete_chain(path, writers, 12)


def test_many_concurrent_applications_still_apply_exactly_once(tmp_path):
    folder = tmp_path / "skills" / "demo"; folder.mkdir(parents=True)
    old, new = "---\nid: demo\n---\nold", "---\nid: demo\n---\nnew"
    (folder / "SKILL.md").write_text(old, encoding="utf-8")
    governance = Governance(tmp_path / "skills", tmp_path / "archive", AuditLedger(tmp_path / "audit.jsonl"),
                            approval_key=KEY)
    proposal = propose_skill_update("demo", old, new, "contention")
    approval = governance.issue_approval(proposal, "me", True, "reviewed")

    def apply_once():
        try:
            governance.apply(proposal, approval)
            return "applied"
        except GovernanceError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=16) as pool:
        outcomes = list(pool.map(lambda _: apply_once(), range(16), timeout=120))
    assert outcomes.count("applied") == 1
    assert sum("Stale proposal" in value for value in outcomes) == 15
    assert (folder / "SKILL.md").read_text(encoding="utf-8") == new
    assert governance.audit.verify()


def test_many_concurrent_revocations_are_all_kept(tmp_path):
    key_ids = [key_identifier(bytes([n]) * 40) for n in range(1, 17)]

    def revoke(index):
        gov = Governance(tmp_path / "skills", tmp_path / f"archive-{index}",
                         AuditLedger(tmp_path / f"audit-{index}.jsonl"))
        return gov.revoke_approval_key(key_ids[index], "rotation")["status"]

    with ThreadPoolExecutor(max_workers=16) as pool:
        assert list(pool.map(revoke, range(16), timeout=120)) == ["key_revoked"] * 16
    assert revocation.revoked_key_ids() == set(key_ids)


def test_audit_governance_and_registry_locks_under_mixed_contention(tmp_path):
    """Writers on one ledger while signing (governance + registry + audit locks) and revoking run alongside."""
    folder = tmp_path / "skills" / "demo"; folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nid: demo\n---\nold", encoding="utf-8")
    ledger_path = tmp_path / "audit.jsonl"
    governance = Governance(tmp_path / "skills", tmp_path / "archive", AuditLedger(ledger_path), approval_key=KEY)
    proposals = [propose_skill_update("demo", "---\nid: demo\n---\nold", f"---\nid: demo\n---\nv{n}", "mixed")
                 for n in range(8)]
    other_keys = [key_identifier(bytes([n]) * 40) for n in range(100, 108)]
    tasks = ([lambda w=w: _append_many(ledger_path, w, 12) for w in range(8)]
             + [lambda p=p: governance.issue_approval(p, "me", True, "reviewed") for p in proposals]
             + [lambda k=k: governance.revoke_approval_key(k, "rotation") for k in other_keys])
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        for future in [pool.submit(task) for task in tasks]:
            future.result(timeout=120)
    ledger = AuditLedger(ledger_path)
    assert ledger.verify()
    types = [event["type"] for event in ledger._events()]
    assert types.count("concurrency") == 96
    assert types.count("proposal_approval_signed") == 8
    assert types.count("approval_key_revoked") == 8
    assert set(other_keys) <= revocation.revoked_key_ids()


# --- Cleanup under repeated interruption (Windows) -------------------------------------------------

ERROR_IO_INCOMPLETE = 996


@pytest.fixture(autouse=True)
def no_request_left_unsettled():
    yield
    assert not getattr(file_lock, "_UNSETTLED", set()), "every lock request must be fully settled"


class TracingKernel:
    """Wraps the real kernel32, injects KeyboardInterrupts at chosen calls, and records lifetime violations.

    An OVERLAPPED record handed to the kernel is outstanding until a GetOverlappedResult call shows it
    complete. Closing its file or event handle, or freeing it, while it is outstanding is a violation.
    The tracer keeps only weak references, so a record freed by the code under test is noticed.
    """

    def __init__(self, real):
        self.real = real
        self.calls = []        # calls made by this thread; lifetime checks cover all threads
        self.outstanding = {}  # id(record) -> (weakref to record, file handle, event handle, call name)
        self.violations = []
        self.interrupts = []   # [name, phase, predicate, remaining]
        self.overrides = {}    # name -> function(real_function, *args) -> (result, last_error)
        self.thread = threading.get_ident()  # like Ctrl+C, injected interrupts reach only this thread

    def interrupt(self, name, phase, times=1, when=lambda args: True):
        self.interrupts.append([name, phase, when, times])

    def _maybe_interrupt(self, name, phase, args):
        for rule in self.interrupts if threading.get_ident() == self.thread else ():
            if rule[0] == name and rule[1] == phase and rule[3] > 0 and rule[2](args):
                rule[3] -= 1
                raise KeyboardInterrupt(f"injected {phase} {name}")

    def __getattr__(self, name):
        real = getattr(self.real, name)

        def call(*args):
            self._maybe_interrupt(name, "before", args)
            if name == "CloseHandle":
                self._check_close(args[0])
            if name in self.overrides:
                result, error = self.overrides[name](real, *args)
            else:
                result = real(*args)
                error = ctypes.get_last_error()
            if threading.get_ident() == self.thread:
                self.calls.append((name, args, result, error))
            self._observe(name, args, result, error)
            ctypes.set_last_error(error)
            self._maybe_interrupt(name, "after", args)
            return result
        return call

    def _observe(self, name, args, result, error):
        if name in ("LockFileEx", "UnlockFileEx") and not result and error == 997:
            record = args[-1]._obj
            self.outstanding[id(record)] = (weakref.ref(record), args[0], record.hEvent, name)
        elif name == "GetOverlappedResult" and (result or error != ERROR_IO_INCOMPLETE):
            entry = self.outstanding.pop(id(args[1]._obj), None)
            if entry and entry[0]() is None:
                self.violations.append(f"{entry[3]} record was freed before it completed")

    def _check_close(self, handle):
        for ref, file_handle, event, name in self.outstanding.values():
            if handle in (file_handle, event):
                self.violations.append(f"handle closed while {name} was outstanding")

    def assert_clean(self):
        unfired = [f"{rule[1]} {rule[0]} x{rule[3]}" for rule in self.interrupts if rule[3]]
        self.interrupts.clear()
        assert not unfired, f"injected interrupts that never fired: {unfired}"
        for ref, _, _, name in self.outstanding.values():
            self.violations.append(f"{name} never observed complete" + (" (record freed)" if ref() is None else ""))
        assert not self.violations, self.violations

    def names(self):
        return [call[0] for call in self.calls]


@pytest.fixture
def tracer(monkeypatch):
    tracing = TracingKernel(file_lock._kernel32())
    monkeypatch.setattr(file_lock, "_kernel32", lambda: tracing)
    return tracing


def interrupt_first_wait(monkeypatch):
    """The first Ctrl+C arrives while waiting for the lock."""
    def interrupted(event, milliseconds):
        raise KeyboardInterrupt("first interrupt")
    monkeypatch.setattr(file_lock, "_wait", interrupted)


def assert_lock_free(lock, within=0.25):
    started = time.monotonic()
    with exclusive_lock(lock, timeout=2):
        assert time.monotonic() - started < within, "the lock must have been given back"


def waits(args):
    return bool(args[-1])


@windows_only
def test_second_interrupt_right_after_cancel_still_waits_for_completion(tmp_path, monkeypatch, tracer):
    lock = tmp_path / "x.lock"
    thread, _ = hold_in_thread(lock, 0.8)
    interrupt_first_wait(monkeypatch)
    tracer.interrupt("CancelIoEx", "after")
    with pytest.raises(KeyboardInterrupt, match="first interrupt"):
        with exclusive_lock(lock):
            pytest.fail("body must not run")
    tracer.assert_clean()
    thread.join()
    assert_lock_free(lock)


@windows_only
def test_interrupt_before_the_cancellation_wait_begins(tmp_path, monkeypatch, tracer):
    lock = tmp_path / "x.lock"
    thread, _ = hold_in_thread(lock, 0.8)
    interrupt_first_wait(monkeypatch)
    tracer.interrupt("GetOverlappedResult", "before", when=waits)
    with pytest.raises(KeyboardInterrupt, match="first interrupt"):
        with exclusive_lock(lock):
            pytest.fail("body must not run")
    tracer.assert_clean()
    thread.join()
    assert_lock_free(lock)


@windows_only
def test_interrupts_at_every_cleanup_step(tmp_path, monkeypatch, tracer):
    lock = tmp_path / "x.lock"
    thread, _ = hold_in_thread(lock, 0.8)
    interrupt_first_wait(monkeypatch)
    for name, phase in [("CancelIoEx", "before"), ("CancelIoEx", "after"), ("GetOverlappedResult", "before"),
                        ("GetOverlappedResult", "after"), ("CloseHandle", "after")]:
        tracer.interrupt(name, phase, times=2)
    with pytest.raises(KeyboardInterrupt, match="first interrupt"):
        with exclusive_lock(lock):
            pytest.fail("body must not run")
    thread.join()
    tracer.assert_clean()
    assert tracer.names().count("CloseHandle") == 2
    assert_lock_free(lock)


@windows_only
def test_a_handle_is_never_closed_twice_when_closing_is_interrupted(tmp_path, tracer):
    lock = tmp_path / "x.lock"
    tracer.interrupt("CloseHandle", "before")  # the earliest an interruption could land
    with pytest.raises(KeyboardInterrupt):
        with exclusive_lock(lock):
            pass
    tracer.assert_clean()
    closed = [call[1][0] for call in tracer.calls if call[0] == "CloseHandle"]
    assert len(closed) == len(set(closed)) == 1, "the other handle is leaked, never closed twice"
    assert_lock_free(lock)


@windows_only
def test_grant_racing_cleanup_is_given_back_despite_repeated_interrupts(tmp_path, monkeypatch, tracer):
    lock = tmp_path / "x.lock"
    release, held = threading.Event(), threading.Event()

    def holder():
        with exclusive_lock(lock):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder); thread.start()
    assert held.wait(5)

    def grant_then_interrupt(event, milliseconds):
        release.set()
        thread.join(5)
        tracer.real.WaitForSingleObject(event, 2000)  # the pending request is granted here
        raise KeyboardInterrupt("first interrupt")

    monkeypatch.setattr(file_lock, "_wait", grant_then_interrupt)
    tracer.interrupt("GetOverlappedResult", "after", when=waits)  # the cancellation wait's result is lost
    tracer.interrupt("UnlockFileEx", "after")                      # the unlock's result is lost
    with pytest.raises(KeyboardInterrupt, match="first interrupt"):
        with exclusive_lock(lock):
            pytest.fail("body must not run")
    tracer.assert_clean()
    assert any(name == "UnlockFileEx" and result for name, _, result, _ in tracer.calls)
    assert_lock_free(lock)


def report_pending(real, *args):
    """UnlockFileEx that unlocks, then reports ERROR_IO_PENDING, which the API permits."""
    real(*args)
    return 0, 997


@windows_only
def test_pending_unlock_completes_before_handles_close_despite_an_interrupt(tmp_path, tracer):
    lock = tmp_path / "x.lock"
    tracer.overrides["UnlockFileEx"] = report_pending
    tracer.interrupt("GetOverlappedResult", "before", when=waits)
    with pytest.raises(KeyboardInterrupt, match="injected before GetOverlappedResult"):
        with exclusive_lock(lock):
            pass
    tracer.assert_clean()
    names = tracer.names()
    last_wait = len(names) - 1 - names[::-1].index("GetOverlappedResult")
    assert names.index("UnlockFileEx") < last_wait < names.index("CloseHandle")
    tracer.overrides.clear()
    assert_lock_free(lock)


@windows_only
def test_interrupt_right_after_an_immediate_grant_unlocks_before_closing(tmp_path, tracer):
    lock = tmp_path / "x.lock"
    tracer.interrupt("LockFileEx", "after")  # granted at once, but the result is lost
    with pytest.raises(KeyboardInterrupt):
        with exclusive_lock(lock):
            pytest.fail("body must not run")
    tracer.assert_clean()
    names = tracer.names()
    unlocked = [i for i, call in enumerate(tracer.calls) if call[0] == "UnlockFileEx" and call[2]]
    assert unlocked and unlocked[0] < names.index("CloseHandle"), "the granted lock must be unlocked explicitly"
    assert_lock_free(lock)


@windows_only
def test_a_record_whose_result_was_lost_is_never_freed(tmp_path, tracer):
    lock = tmp_path / "x.lock"
    tracer.interrupt("LockFileEx", "after")
    with pytest.raises(KeyboardInterrupt):
        with exclusive_lock(lock):
            pytest.fail("body must not run")
    lock_record = next(call[1][-1]._obj for call in tracer.calls if call[0] == "LockFileEx")
    assert any(record is lock_record for record in file_lock._RETAINED)


@windows_only
def test_interrupt_after_the_grant_is_recorded_unlocks_before_closing(tmp_path, monkeypatch, tracer):
    lock = tmp_path / "x.lock"
    real_acquire = file_lock._acquire

    def acquire_then_interrupt(request, timeout):
        real_acquire(request, timeout)
        raise KeyboardInterrupt("before the body")

    monkeypatch.setattr(file_lock, "_acquire", acquire_then_interrupt)
    with pytest.raises(KeyboardInterrupt, match="before the body"):
        with exclusive_lock(lock):
            pytest.fail("body must not run")
    monkeypatch.setattr(file_lock, "_acquire", real_acquire)
    names = tracer.names()
    assert "UnlockFileEx" in names and names.index("UnlockFileEx") < names.index("CloseHandle")
    assert tracer.calls[names.index("UnlockFileEx")][2], "the unlock must succeed"
    assert_lock_free(lock)


def fail_unlock(real, *args):
    return 0, 33  # ERROR_LOCK_VIOLATION, without unlocking


@windows_only
def test_unlock_failure_is_reported_and_the_handles_still_closed(tmp_path, tracer):
    lock = tmp_path / "x.lock"
    tracer.overrides["UnlockFileEx"] = fail_unlock
    ran = []
    with pytest.raises(file_lock.LockReleaseError, match="UnlockFileEx failed") as error:
        with exclusive_lock(lock):
            ran.append(True)
    assert ran and isinstance(error.value, OSError)
    assert "protected work finished" in str(error.value)
    assert tracer.names().count("CloseHandle") == 2
    tracer.overrides.clear()
    assert_lock_free(lock, within=2)  # closing the handle released the lock


@windows_only
def test_unlock_failure_is_noted_on_an_exception_already_propagating(tmp_path, tracer):
    lock = tmp_path / "x.lock"
    tracer.overrides["UnlockFileEx"] = fail_unlock
    with pytest.raises(ValueError, match="work failed") as error:
        with exclusive_lock(lock):
            raise ValueError("work failed")
    assert any("UnlockFileEx failed" in note for note in error.value.__notes__)
    assert tracer.names().count("CloseHandle") == 2
    tracer.overrides.clear()
    assert_lock_free(lock, within=2)


@windows_only
def test_deadline_is_for_acquisition_and_cleanup_still_completes(tmp_path, tracer):
    lock = tmp_path / "x.lock"
    thread, _ = hold_in_thread(lock, 1.5)

    def slow_cancellation(real, *args):
        if args[-1]:
            time.sleep(0.5)  # cancellation takes a while to complete
        result = real(*args)
        return result, ctypes.get_last_error()

    tracer.overrides["GetOverlappedResult"] = slow_cancellation
    started = time.monotonic()
    with pytest.raises(LockTimeoutError):
        with exclusive_lock(lock, timeout=0.3):
            pytest.fail("body must not run")
    assert time.monotonic() - started >= 0.75, "the call returns only once cancellation has completed"
    tracer.assert_clean()
    thread.join()


@windows_only
def test_interrupt_during_timeout_cleanup_is_raised_with_the_timeout_as_context(tmp_path, tracer):
    lock = tmp_path / "x.lock"
    thread, _ = hold_in_thread(lock, 1.0)
    tracer.interrupt("CancelIoEx", "after")
    with pytest.raises(KeyboardInterrupt) as error:
        with exclusive_lock(lock, timeout=0.3):
            pytest.fail("body must not run")
    assert isinstance(error.value.__context__, LockTimeoutError)
    tracer.assert_clean()
    thread.join()


@windows_only
def test_escaped_cleanup_keeps_the_request_until_it_is_settled_at_exit(tmp_path, monkeypatch, tracer):
    lock = tmp_path / "x.lock"
    release, held = threading.Event(), threading.Event()

    def holder():
        with exclusive_lock(lock):
            held.set()
            release.wait(5)

    thread = threading.Thread(target=holder); thread.start()
    assert held.wait(5)
    interrupt_first_wait(monkeypatch)
    real_settle = file_lock._settle

    def escape(request):
        raise KeyboardInterrupt("cleanup escaped")

    monkeypatch.setattr(file_lock, "_settle", escape)
    with pytest.raises(KeyboardInterrupt, match="cleanup escaped"):
        with exclusive_lock(lock):
            pytest.fail("body must not run")
    monkeypatch.setattr(file_lock, "_settle", real_settle)
    abandoned = [r for r in file_lock._UNSETTLED if r.owner is threading.current_thread()]
    assert len(abandoned) == 1 and abandoned[0].handle, "the request and its handle must be kept"
    gc.collect()
    assert not [c for c in tracer.calls if c[0] == "CloseHandle" and c[1][0] == abandoned[0].handle]
    release.set(); thread.join(5)  # the abandoned request may now be granted
    file_lock._settle_abandoned()
    tracer.assert_clean()
    assert not file_lock._UNSETTLED
    assert_lock_free(lock)
