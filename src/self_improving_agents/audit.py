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
            # append() always ends a record with "\n"; anything else is a torn tail, and appending
            # after it would merge two records into one unrecoverable line.
            if self.path.exists() and self.path.stat().st_size and not self.path.read_bytes().endswith(b"\n"):
                return False
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

    def _verified_events(self, text: str) -> list[dict]:
        """Parse complete ledger lines, raising ValueError on any malformed line or chain break."""
        events, previous = [], "0" * 64
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            event = json.loads(line)
            if (not isinstance(event, dict) or event.get("seq") != len(events) + 1
                    or event.get("previous_hash") != previous):
                raise ValueError(f"audit chain broken at line {line_number}")
            base = {key: value for key, value in event.items() if key != "event_hash"}
            if event.get("event_hash") != self._hash_event(base):
                raise ValueError(f"audit hash mismatch at line {line_number}")
            previous = event["event_hash"]
            events.append(event)
        return events

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass

    @classmethod
    def _durable_write(cls, path: Path, data: bytes) -> None:
        with path.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        cls._fsync_directory(path.parent)

    def recover_torn_tail(self) -> dict:
        """Operator recovery for a partial final line left by a crash; never runs automatically.

        Only bytes after the last newline are treated as torn, because append() writes each
        event and its newline in one write. Anything wrong before that point is refused.
        The original file is preserved byte-for-byte and the recovery is itself audited.
        """
        with self._exclusive_lock():
            if not self.path.exists():
                return {"status": "clean", "reason": "ledger does not exist"}
            original = self.path.read_bytes()
            cut = original.rfind(b"\n") + 1
            prefix, tail = original[:cut], original[cut:]
            try:
                events = self._verified_events(prefix.decode("utf-8"))
            except (UnicodeError, ValueError) as exc:
                return {"status": "refused", "reason": f"ledger before the final line is not intact: {exc}"}
            if not tail:
                return {"status": "clean", "reason": "no partial final line"}

            completed = None
            try:
                candidate = json.loads(tail.decode("utf-8"))
                completed = self._verified_events(prefix.decode("utf-8") + json.dumps(candidate) + "\n")[-1]
            except (UnicodeError, ValueError, IndexError):
                completed = None

            original_sha256 = sha256(original).hexdigest()
            quarantine = self.path.with_name(f"{self.path.name}.torn-{original_sha256[:16]}.bak")
            if quarantine.exists():
                if sha256(quarantine.read_bytes()).hexdigest() != original_sha256:
                    return {"status": "refused", "reason": f"quarantine {quarantine.name} exists with different bytes"}
            else:
                # Preserve the original before any replacement, and prove the copy is exact.
                partial = quarantine.with_name(quarantine.name + ".partial")
                try:
                    self._durable_write(partial, original)
                    if sha256(partial.read_bytes()).hexdigest() != original_sha256:
                        raise OSError("backup read-back does not match the original ledger")
                    os.replace(partial, quarantine)
                except OSError as exc:
                    partial.unlink(missing_ok=True)
                    return {"status": "refused", "reason": f"could not preserve the original ledger: {exc}"}

            kept = prefix + tail + b"\n" if completed else prefix
            chain = events + [completed] if completed else events
            event = {
                "seq": len(chain) + 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "audit_tail_completed" if completed else "audit_tail_truncated",
                "payload": {
                    "original_sha256": original_sha256,
                    "original_bytes": len(original),
                    "removed_bytes": 0 if completed else len(tail),
                    "removed_sha256": None if completed else sha256(tail).hexdigest(),
                    "quarantine": quarantine.name,
                },
                "previous_hash": chain[-1]["event_hash"] if chain else "0" * 64,
            }
            event["event_hash"] = self._hash_event(event)
            line = (json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
            temp = self.path.with_name(self.path.name + ".recover.tmp")
            try:
                self._durable_write(temp, kept + line)
                os.replace(temp, self.path)
            except Exception:
                temp.unlink(missing_ok=True)
                raise
            self._fsync_directory(self.path.parent)
            return {"status": "recovered", "action": event["type"], "quarantine": str(quarantine),
                    "removed_bytes": event["payload"]["removed_bytes"]}
