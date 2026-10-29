"""Append-only JSONL hash-chain audit ledger with cross-process writer locking."""
from __future__ import annotations
import json
import os
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone
from contextlib import contextmanager


class AuditIntegrityError(RuntimeError):
    """Raised when an append is attempted against a corrupted ledger."""


class AuditLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.path.with_name(self.path.name + ".lock")

    @contextmanager
    def _exclusive_lock(self):
        """Serialize ledger reads/writes across processes on Windows and POSIX."""
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock_file:
            if os.name == "nt":
                import msvcrt
                # Lock byte 0 without writing it first: Windows allows locking past EOF, and
                # an unlocked initialisation write can collide with another holder's lock.
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _events(self) -> list[dict]:
        if not self.path.exists():
            return []
        events = []
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed audit JSON at line {line_number}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"Audit event at line {line_number} is not an object")
            events.append(event)
        return events

    @staticmethod
    def _hash_event(event: dict) -> str:
        canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return sha256(canonical.encode("utf-8")).hexdigest()

    def append(self, event_type: str, payload: dict) -> dict:
        with self._exclusive_lock():
            if not self._verify_unlocked():
                raise AuditIntegrityError("Audit ledger failed integrity verification; refusing to append")
            events = self._events()
            previous = events[-1]["event_hash"] if events else "0" * 64
            event = {
                "seq": len(events) + 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": event_type,
                "payload": payload,
                "previous_hash": previous,
            }
            event["event_hash"] = self._hash_event(event)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return event

    def _verify_unlocked(self) -> bool:
        previous = "0" * 64
        try:
            events = self._events()
        except (OSError, UnicodeError, ValueError):
            return False
        for index, event in enumerate(events, start=1):
            if event.get("seq") != index or event.get("previous_hash") != previous:
                return False
            claimed = event.get("event_hash")
            if not isinstance(claimed, str):
                return False
            base = {key: value for key, value in event.items() if key != "event_hash"}
            if self._hash_event(base) != claimed:
                return False
            previous = claimed
        return True

    def verify(self) -> bool:
        with self._exclusive_lock():
            return self._verify_unlocked()
