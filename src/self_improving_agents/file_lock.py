"""Cross-process exclusive file locks that wait for the holder instead of polling.

On Windows the lock is a byte-range lock on byte 0 (length 1) of the lock file, requested with
LockFileEx on an overlapped handle. The kernel completes the request as soon as the holder
releases, so waiters are woken promptly; msvcrt.locking(LK_LOCK) instead retried once a second
and gave up after ten tries, which turned contention into a one-writer-per-second convoy. The byte
range matches msvcrt.locking(..., 1) at offset 0, so older code that still uses msvcrt.locking on
the same file excludes, and is excluded by, this lock. The locked byte is never written.

The timeout is an acquisition deadline: once it passes, no further wait for the lock is started
and the attempt fails closed with LockTimeoutError (an OSError), with nothing done under the lock.
It is not a bound on how long the call takes to return. A request still pending at the deadline is
cancelled, and the call waits for the cancellation to complete before freeing the request's memory
and closing its handles, because the kernel may still write to them; under abnormal driver or
storage conditions that wait can be longer.

Cleanup tolerates further interruptions (such as a second Ctrl+C): each lock request, with every
OVERLAPPED record handed to the kernel, stays registered until it has been unlocked if it was ever
granted, its outstanding operations have completed, and its handles are closed. An interruption
that escapes even the retrying cleanup can therefore delay a release, but never free a record or
close a handle the kernel may still use; such a request is settled at interpreter exit (or released
by the OS when the process ends). An unexpected unlock failure is reported (LockReleaseError, or a
note on the exception already propagating), and the handles are still closed, which releases the
lock, possibly after a delay.

A process that exits or is killed releases its locks. On POSIX the lock is fcntl.flock(LOCK_EX),
unchanged (it blocks without polling, with no deadline).
"""
from __future__ import annotations
import functools
import os
import time
from contextlib import contextmanager
from pathlib import Path

LOCK_TIMEOUT_SECONDS = 10.0
_WAIT_SLICE_MS = 100  # wake periodically only so Ctrl+C and the deadline are honoured


class LockTimeoutError(TimeoutError):
    """The lock was not granted before the acquisition deadline; nothing was done under it."""


class LockReleaseError(OSError):
    """Unlocking failed after the protected work finished; the handle was still closed."""


if os.name == "nt":
    import atexit
    import ctypes
    import threading
    from ctypes import wintypes

    _GENERIC_READ, _GENERIC_WRITE = 0x80000000, 0x40000000
    _FILE_SHARE_READ, _FILE_SHARE_WRITE = 0x1, 0x2
    _OPEN_ALWAYS, _FILE_ATTRIBUTE_NORMAL, _FILE_FLAG_OVERLAPPED = 4, 0x80, 0x40000000
    _LOCKFILE_EXCLUSIVE_LOCK = 0x2
    _ERROR_NOT_LOCKED, _ERROR_IO_PENDING = 158, 997
    _WAIT_OBJECT_0, _WAIT_TIMEOUT = 0x0, 0x102
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    _SETTLE_ATTEMPTS = 100  # bounds retries if a cleanup step itself keeps failing

    class _OVERLAPPED(ctypes.Structure):
        _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                    ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD), ("hEvent", wintypes.HANDLE)]

    @functools.lru_cache(maxsize=1)
    def _kernel32():
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateEventW.restype = wintypes.HANDLE
        k.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.DWORD, ctypes.POINTER(_OVERLAPPED)]
        k.LockFileEx.restype = wintypes.BOOL
        k.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.POINTER(_OVERLAPPED)]
        k.UnlockFileEx.restype = wintypes.BOOL
        k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.WaitForSingleObject.restype = wintypes.DWORD
        k.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED),
                                          ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
        k.GetOverlappedResult.restype = wintypes.BOOL
        k.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(_OVERLAPPED)]
        k.CancelIoEx.restype = wintypes.BOOL
        k.ResetEvent.argtypes = [wintypes.HANDLE]
        k.ResetEvent.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        return k

    def _wait(event, milliseconds: int) -> int:
        return _kernel32().WaitForSingleObject(event, milliseconds)

    def _finish(k, handle, overlapped) -> bool:
        """Block until a pending request on overlapped completes; True if it succeeded."""
        transferred = wintypes.DWORD()
        return bool(k.GetOverlappedResult(handle, ctypes.byref(overlapped), ctypes.byref(transferred), True))

    # A request's state is recorded before each kernel call, so cleanup can tell what may still be
    # outstanding even when an interruption loses the call's result.
    _OPEN, _LOCK_ISSUED, _LOCK_PENDING, _HELD, _UNLOCK_ISSUED, _UNLOCK_PENDING, _RELEASED, _CLOSED = range(8)

    # Requests not yet settled. Holding them here keeps their OVERLAPPED records alive whatever
    # happens to the frames that created them.
    _UNSETTLED: set = set()
    # Records of calls whose result was lost to an interruption. Their completion was never
    # observed, so they are never freed.
    _RETAINED: list = []

    class _Request:
        def __init__(self, path: Path):
            self.path = path
            self.owner = threading.current_thread()
            self.handle = self.event = None
            self.state = _OPEN
            self.records = []  # every OVERLAPPED handed to the kernel for this request
            self.result_lost = False
            self.may_be_unlocked = False  # then ERROR_NOT_LOCKED from an unlock is an answer, not a failure
            self.problems = []

        def new_record(self):
            record = _OVERLAPPED(hEvent=self.event)
            self.records.append(record)
            return record

    @contextmanager
    def exclusive_lock(path: str | Path, timeout: float | None = None):
        request = _Request(Path(path))
        try:
            _acquire(request, LOCK_TIMEOUT_SECONDS if timeout is None else timeout)
            yield
        except BaseException as exc:
            late = _settle(request)
            if request.problems:
                exc.add_note(_release_problem(request))
            if late is not None and isinstance(exc, Exception) and not isinstance(late, Exception):
                raise late  # e.g. Ctrl+C during cleanup after an error; the error stays as its __context__
            raise
        late = _settle(request)
        if late is not None:
            raise late
        if request.problems:
            raise LockReleaseError("The protected work finished, but " + _release_problem(request))

    def _release_problem(request) -> str:
        return (f"releasing the lock on {request.path} failed: {'; '.join(dict.fromkeys(request.problems))}. "
                "The handle was closed, which releases the lock, possibly after a delay.")

    def _acquire(request, timeout: float) -> None:
        k = _kernel32()
        deadline = time.monotonic() + timeout
        _UNSETTLED.add(request)
        request.handle = k.CreateFileW(str(request.path), _GENERIC_READ | _GENERIC_WRITE,
                                       _FILE_SHARE_READ | _FILE_SHARE_WRITE, None, _OPEN_ALWAYS,
                                       _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OVERLAPPED, None)
        if request.handle in (None, _INVALID_HANDLE_VALUE):
            request.handle = None
            raise ctypes.WinError(ctypes.get_last_error())
        request.event = k.CreateEventW(None, True, False, None)
        if not request.event:
            raise ctypes.WinError(ctypes.get_last_error())
        record = request.new_record()
        pointer = ctypes.byref(record)
        request.state = _LOCK_ISSUED
        if k.LockFileEx(request.handle, _LOCKFILE_EXCLUSIVE_LOCK, 0, 1, 0, pointer):
            request.state = _HELD
            return
        error = ctypes.get_last_error()
        if error != _ERROR_IO_PENDING:
            request.state = _RELEASED  # refused outright; nothing outstanding
            raise ctypes.WinError(error)
        request.state = _LOCK_PENDING
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LockTimeoutError(f"Timed out after {timeout:g} s waiting for the lock on {request.path}")
            result = _wait(request.event, max(1, min(_WAIT_SLICE_MS, int(remaining * 1000))))
            if result == _WAIT_OBJECT_0:
                transferred = wintypes.DWORD()
                if not k.GetOverlappedResult(request.handle, pointer, ctypes.byref(transferred), False):
                    raise ctypes.WinError(ctypes.get_last_error())  # cleanup confirms the completion
                request.state = _HELD
                return
            if result != _WAIT_TIMEOUT:
                raise ctypes.WinError(ctypes.get_last_error())

    def _settle(request) -> BaseException | None:
        """Bring request to _CLOSED despite further interruptions; return the first one caught.

        If an interruption escapes this loop, or the attempts run out, the request stays registered:
        nothing it handed to the kernel is freed or closed, and it is settled at interpreter exit.
        """
        late = None
        for _ in range(_SETTLE_ATTEMPTS):
            try:
                k = _kernel32()
                while request.state != _CLOSED:
                    _advance(k, request)
                return late
            except BaseException as exc:  # e.g. another Ctrl+C: finish cleaning up first
                if late is None:
                    late = exc
        return late

    def _advance(k, request) -> None:
        """Take one cleanup step. A step is safe to repeat if an interruption hides its outcome."""
        state = request.state
        if state == _OPEN:
            request.state = _RELEASED
        elif state == _LOCK_ISSUED:
            # LockFileEx may or may not have run, and its result was lost.
            request.result_lost = True
            if k.CancelIoEx(request.handle, ctypes.byref(request.records[-1])):
                request.state = _LOCK_PENDING  # it was pending: now cancelled, or granted meanwhile
            else:
                request.may_be_unlocked = True  # nothing outstanding; the unlock shows whether it was granted
                request.state = _HELD
        elif state == _LOCK_PENDING:
            # Cancel (no effect once complete), then wait until the kernel is done with the record.
            k.CancelIoEx(request.handle, ctypes.byref(request.records[-1]))
            request.state = _HELD if _finish(k, request.handle, request.records[-1]) else _RELEASED
        elif state == _HELD:
            k.ResetEvent(request.event)
            pointer = ctypes.byref(request.new_record())
            request.state = _UNLOCK_ISSUED
            if k.UnlockFileEx(request.handle, 0, 1, 0, pointer):
                request.state = _RELEASED
                return
            error = ctypes.get_last_error()
            if error == _ERROR_IO_PENDING:
                request.state = _UNLOCK_PENDING
                return
            if not (error == _ERROR_NOT_LOCKED and request.may_be_unlocked):
                request.problems.append(f"UnlockFileEx failed: {ctypes.WinError(error)}")
            request.state = _RELEASED
        elif state == _UNLOCK_ISSUED:
            # UnlockFileEx may or may not have run, and its result was lost: unlock again.
            request.result_lost = request.may_be_unlocked = True
            request.state = _HELD
        elif state == _UNLOCK_PENDING:
            if not _finish(k, request.handle, request.records[-1]):
                request.problems.append(f"UnlockFileEx failed: {ctypes.WinError(ctypes.get_last_error())}")
            request.state = _RELEASED
        elif state == _RELEASED:
            # Each field is cleared just before its handle is closed, with no Python call in between, so
            # a repeated step never closes a handle twice; an interruption could at most leak one.
            event, request.event = request.event, None
            if event and not k.CloseHandle(event):
                request.problems.append(f"CloseHandle failed: {ctypes.WinError(ctypes.get_last_error())}")
            handle, request.handle = request.handle, None
            if handle and not k.CloseHandle(handle):
                request.problems.append(f"CloseHandle failed: {ctypes.WinError(ctypes.get_last_error())}")
            if request.result_lost:
                _RETAINED.extend(request.records)
            request.state = _CLOSED
            _UNSETTLED.discard(request)

    def _settle_abandoned() -> None:
        """At interpreter exit, settle requests whose cleanup escaped (main thread or finished threads)."""
        main = threading.main_thread()
        for request in list(_UNSETTLED):
            if request.owner is main or not request.owner.is_alive():
                _settle(request)

    atexit.register(_settle_abandoned)

else:
    import fcntl

    @contextmanager
    def exclusive_lock(path: str | Path, timeout: float | None = None):
        held = _acquire(Path(path), LOCK_TIMEOUT_SECONDS if timeout is None else timeout)
        try:
            yield
        finally:
            _release(held)

    def _acquire(path: Path, timeout: float):
        stream = path.open("a+b")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        except BaseException:
            stream.close()
            raise
        return stream

    def _release(stream) -> None:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()
