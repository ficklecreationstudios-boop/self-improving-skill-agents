"""Skill updates require signed approval, a serialized writer lock, and recovery journals."""
from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
import json
import os
import re
import tempfile
from ..models import Proposal, Approval, digest_text
from ..audit import AuditLedger
from ..skills import discover_skills
from ..approval_auth import sign_approval, verify_approval, key_identifier, ApprovalSignatureError

class GovernanceError(RuntimeError):
    pass


class Governance:
    def __init__(self, skill_root: str | Path, archive_root: str | Path, audit: AuditLedger,
                 approval_key: bytes | None = None):
        self.skill_root = Path(skill_root).resolve()
        self.archive_root = Path(archive_root).resolve()
        self.audit = audit
        self.approval_key = approval_key
        self.lock_path = self.archive_root / ".governance.lock"

    @contextmanager
    def _update_lock(self):
        self.archive_root.mkdir(parents=True, exist_ok=True)
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

    def _assert_key_active(self, key: bytes) -> str:
        if not self.audit.verify():
            raise GovernanceError("Audit ledger failed integrity verification; refusing approval-key use")
        key_id = key_identifier(key)
        try:
            revoked = {
                event.get("payload", {}).get("key_id")
                for event in self.audit._events()
                if event.get("type") == "approval_key_revoked"
            }
        except Exception as exc:
            raise GovernanceError("Cannot read approval-key revocation state; failing closed") from exc
        if key_id in revoked:
            raise GovernanceError("Approval key is revoked; refusing to sign or apply proposals")
        return key_id

    def issue_approval(self, proposal: Proposal, approver: str, approved: bool, reason: str = "") -> Approval:
        if not isinstance(approver, str) or not approver.strip():
            raise GovernanceError("Approver identity label must be non-empty")
        if not approved:
            return Approval(proposal.proposal_digest, approver.strip(), False, reason)
        if self.approval_key is None:
            raise GovernanceError("Approval signing key is not configured")
        try:
            self._assert_key_active(self.approval_key)
            return sign_approval(Approval(proposal.proposal_digest, approver.strip(), True, reason),
                                 self.approval_key)
        except ApprovalSignatureError as exc:
            raise GovernanceError(str(exc)) from exc

    def revoke_approval_key(self, key_id: str, reason: str) -> dict:
        """Record key revocation under the same governance lock used by apply()."""
        if not isinstance(key_id, str) or not re.fullmatch(r"[0-9a-f]{64}", key_id):
            raise GovernanceError("key_id must be a full 64-character lowercase SHA-256 identifier")
        if not isinstance(reason, str) or not reason.strip():
            raise GovernanceError("Revocation reason must be non-empty")
        with self._update_lock():
            if not self.audit.verify():
                raise GovernanceError("Audit ledger is invalid; refusing to revoke key")
            events = self.audit._events()
            if any(event.get("type") == "approval_key_revoked"
                   and event.get("payload", {}).get("key_id") == key_id for event in events):
                return {"status": "already_revoked", "key_id": key_id}
            event = self.audit.append("approval_key_revoked", {
                "key_id": key_id, "reason": reason.strip(),
            })
            return {"status": "key_revoked", "key_id": key_id,
                    "audit_seq": event["seq"], "audit_valid": self.audit.verify()}

    def _find_target(self, skill_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", skill_id):
            raise GovernanceError("Unsafe skill id")
        metadata_ids = {Path(skill.path).resolve(): skill.skill_id for skill in discover_skills(self.skill_root)}
        matches = []
        for candidate in self.skill_root.rglob("SKILL.md"):
            try:
                resolved = candidate.resolve(strict=True)
                resolved.relative_to(self.skill_root)
            except (OSError, ValueError):
                continue
            if resolved.parent.name == skill_id or metadata_ids.get(resolved) == skill_id:
                matches.append(resolved)
        unique = list(dict.fromkeys(matches))
        if len(unique) != 1:
            raise GovernanceError(f"Expected exactly one skill target for {skill_id!r}; found {len(unique)}")
        return unique[0]

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
    def _atomic_write(cls, target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".skill-update-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
            cls._fsync_directory(target.parent)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def _write_journal(self, journal_path: Path, record: dict) -> None:
        self._atomic_write(journal_path, json.dumps(record, sort_keys=True, indent=2) + "\n")

    def recover_pending(self) -> list[str]:
        with self._update_lock():
            return self._recover_pending_unlocked()

    def _recover_pending_unlocked(self) -> list[str]:
        recovered: list[str] = []
        for journal_path in sorted(self.archive_root.glob("*.txn.json")):
            try:
                record = json.loads(journal_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise GovernanceError(f"Cannot read transaction journal {journal_path.name}") from exc
            if record.get("phase") in {"committed", "rolled_back"}:
                continue
            target = Path(record.get("target", "")).resolve()
            archive = Path(record.get("archive", "")).resolve()
            try:
                target.relative_to(self.skill_root)
                archive.relative_to(self.archive_root)
            except ValueError as exc:
                raise GovernanceError("Transaction journal path escapes configured roots") from exc
            if not archive.is_file():
                raise GovernanceError(f"Transaction archive is missing: {archive.name}")
            old_content = archive.read_text(encoding="utf-8")
            old_digest = digest_text(old_content)
            if old_digest != record.get("old_digest"):
                raise GovernanceError(f"Transaction archive digest mismatch: {archive.name}")
            current = target.read_text(encoding="utf-8") if target.exists() else None
            current_digest = digest_text(current) if current is not None else None
            try:
                audit_valid = self.audit.verify()
                events = self.audit._events() if audit_valid else []
            except Exception:
                audit_valid, events = False, []
            committed_event = any(
                event.get("type") == "skill_update_applied"
                and event.get("payload", {}).get("proposal_digest") == record.get("proposal_digest")
                and event.get("payload", {}).get("new_digest") == record.get("new_digest")
                for event in events
            )
            if audit_valid and committed_event:
                if current_digest != record.get("new_digest"):
                    raise GovernanceError(f"Committed skill does not match transaction journal: {target.name}")
                record["phase"] = "committed"
                self._write_journal(journal_path, record)
                recovered.append(f"finalized:{record.get('skill_id')}")
                continue
            if current_digest in {record.get("new_digest"), None}:
                self._atomic_write(target, old_content)
            elif current_digest != old_digest:
                raise GovernanceError(f"Skill changed outside the interrupted transaction: {target.name}")
            if audit_valid:
                self.audit.append("skill_update_recovered_rollback", {
                    "skill_id": record.get("skill_id"), "proposal_digest": record.get("proposal_digest"),
                    "journal": journal_path.name, "restored_digest": old_digest,
                })
            record["phase"] = "rolled_back"
            self._write_journal(journal_path, record)
            recovered.append(f"rolled_back:{record.get('skill_id')}")
        return recovered

    def apply(self, proposal: Proposal, approval: Approval) -> Path:
        with self._update_lock():
            return self._apply_locked(proposal, approval)

    def _apply_locked(self, proposal: Proposal, approval: Approval) -> Path:
        if self.approval_key is None:
            raise GovernanceError("Approval signing key is not configured")
        self._assert_key_active(self.approval_key)
        if approval.key_id and approval.key_id != key_identifier(self.approval_key):
            raise GovernanceError("Approval key identifier does not match the configured key; signature is invalid")
        if not verify_approval(approval, self.approval_key):
            raise GovernanceError("Approval signature is missing or invalid")
        if approval.proposal_digest != proposal.proposal_digest:
            raise GovernanceError("Approval does not bind this exact proposal")
        if proposal.sealed().proposal_digest != proposal.proposal_digest:
            raise GovernanceError("Proposal digest is invalid")
        if not proposal.proposed_content.strip():
            raise GovernanceError("Proposed skill content must not be empty")
        self._recover_pending_unlocked()
        if not self.audit.verify():
            raise GovernanceError("Audit ledger failed integrity verification; refusing skill update")
        target = self._find_target(proposal.skill_id)
        current = target.read_text(encoding="utf-8")
        if digest_text(current) != proposal.base_digest:
            raise GovernanceError("Stale proposal: base skill content has changed")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        archive = self.archive_root / f"{proposal.skill_id}.{stamp}.SKILL.md"
        with archive.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(current); stream.flush(); os.fsync(stream.fileno())
        self._fsync_directory(self.archive_root)
        journal_path = self.archive_root / f"{proposal.skill_id}.{stamp}.txn.json"
        record = {
            "schema": 1, "phase": "prepared", "skill_id": proposal.skill_id,
            "target": str(target), "archive": str(archive), "old_digest": digest_text(current),
            "new_digest": digest_text(proposal.proposed_content), "proposal_digest": proposal.proposal_digest,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_journal(journal_path, record)
        try:
            self._atomic_write(target, proposal.proposed_content)
            record["phase"] = "target_written"
            self._write_journal(journal_path, record)
            self.audit.append("skill_update_applied", {
                "skill_id": proposal.skill_id, "proposal_digest": proposal.proposal_digest,
                "approver": approval.approver, "approval_signature_digest": digest_text(approval.signature),
                "archive": str(archive), "new_digest": digest_text(proposal.proposed_content),
                "transaction_journal": str(journal_path),
            })
        except Exception:
            self._atomic_write(target, current)
            raise
        record["phase"] = "committed"
        try:
            self._write_journal(journal_path, record)
        except Exception as exc:
            raise GovernanceError("Skill update and audit committed; journal finalization needs recovery") from exc
        return target
