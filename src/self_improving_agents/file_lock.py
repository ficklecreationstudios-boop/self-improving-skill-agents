"""Cross-process exclusive file locks that wait for the holder instead of polling.

On Windows the lock is a byte-range lock on byte 0 (length 1) of the lock file, requested with
LockFileEx on an overlapped handle. The kernel completes the request as soon as the holder
releases, so waiters are woken promptly; msvcrt.locking(LK_LOCK) instead retried once a second
and gave up after ten tries, which turned contention into a one-writer-per-second convoy. The
wait has an explicit deadline and fails closed with LockTimeoutError (an OSError). The byte range
matches msvcrt.locking(..., 1) at offset 0, so older code that still uses msvcrt.locking on the
same file excludes, and is excluded by, this lock. The locked byte is never written.

A process that exits or is killed releases its locks, and closing a handle cancels its pending
request. On POSIX the lock is fcntl.flock(LOCK_EX), unchanged (it blocks without polling).
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
    """The lock was not granted before the deadline; nothing was done under it."""


@contextmanager
def exclusive_lock(path: str | Path, timeout: float | None = None):
    held = _acquire(Path(path), LOCK_TIMEOUT_SECONDS if timeout is None else timeout)
    try:
        yield
    finally:
        _release(held)


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _GENERIC_READ, _GENERIC_WRITE = 0x80000000, 0x40000000
    _FILE_SHARE_READ, _FILE_SHARE_WRITE = 0x1, 0x2
    _OPEN_ALWAYS, _FILE_ATTRIBUTE_NORMAL, _FILE_FLAG_OVERLAPPED = 4, 0x80, 0x40000000
    _LOCKFILE_EXCLUSIVE_LOCK = 0x2
    _ERROR_IO_PENDING = 997
    _WAIT_OBJECT_0, _WAIT_TIMEOUT = 0x0, 0x102
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

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

    def _unlock(k, handle, event) -> bool:
        k.ResetEvent(event)
        overlapped = _OVERLAPPED(hEvent=event)
        if k.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped)):
            return True
        return ctypes.get_last_error() == _ERROR_IO_PENDING and _finish(k, handle, overlapped)

    def _wait_for_grant(k, handle, event, overlapped, timeout: float, path: Path) -> None:
        deadline = time.monotonic() + timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LockTimeoutError(f"Timed out after {timeout:g} s waiting for the lock on {path}")
                result = _wait(event, max(1, min(_WAIT_SLICE_MS, int(remaining * 1000))))
                if result == _WAIT_OBJECT_0:
                    transferred = wintypes.DWORD()
                    if not k.GetOverlappedResult(handle, ctypes.byref(overlapped), ctypes.byref(transferred), False):
                        raise ctypes.WinError(ctypes.get_last_error())
                    return
                if result != _WAIT_TIMEOUT:
                    raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            # Cancel the pending request and wait until the kernel is done with `overlapped`.
            # If it was granted in the meantime, give the lock back before failing.
            k.CancelIoEx(handle, ctypes.byref(overlapped))
            if _finish(k, handle, overlapped):
                _unlock(k, handle, event)
            raise

    def _acquire(path: Path, timeout: float):
        k = _kernel32()
        handle = k.CreateFileW(str(path), _GENERIC_READ | _GENERIC_WRITE, _FILE_SHARE_READ | _FILE_SHARE_WRITE,
                               None, _OPEN_ALWAYS, _FILE_ATTRIBUTE_NORMAL | _FILE_FLAG_OVERLAPPED, None)
        if handle in (None, _INVALID_HANDLE_VALUE):
            raise ctypes.WinError(ctypes.get_last_error())
        event = None
        try:
            event = k.CreateEventW(None, True, False, None)
            if not event:
                raise ctypes.WinError(ctypes.get_last_error())
            overlapped = _OVERLAPPED(hEvent=event)
            if not k.LockFileEx(handle, _LOCKFILE_EXCLUSIVE_LOCK, 0, 1, 0, ctypes.byref(overlapped)):
                error = ctypes.get_last_error()
                if error != _ERROR_IO_PENDING:
                    raise ctypes.WinError(error)
                _wait_for_grant(k, handle, event, overlapped, timeout, path)
            return handle, event
        except BaseException:
            if event:
                k.CloseHandle(event)
            k.CloseHandle(handle)
            raise

    def _release(held) -> None:
        handle, event = held
        k = _kernel32()
        try:
            _unlock(k, handle, event)  # closing the handle below releases the lock even if this fails
        finally:
            k.CloseHandle(event)
            k.CloseHandle(handle)

else:
    import fcntl

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
