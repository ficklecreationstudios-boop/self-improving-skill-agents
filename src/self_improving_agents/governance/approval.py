"""Approval-bound skill updates with archived prior versions."""
from pathlib import Path
from datetime import datetime, timezone
import os
import re
import tempfile
from ..models import Proposal, Approval, digest_text
from ..audit import AuditLedger
from ..skills import discover_skills

class GovernanceError(RuntimeError):
    pass


class Governance:
    def __init__(self, skill_root: str | Path, archive_root: str | Path, audit: AuditLedger):
        self.skill_root = Path(skill_root).resolve()
        self.archive_root = Path(archive_root).resolve()
        self.audit = audit

    def issue_approval(self, proposal: Proposal, approver: str, approved: bool, reason: str = "") -> Approval:
        if not approver.strip():
            raise GovernanceError("Approver identity must be non-empty")
        return Approval(proposal.proposal_digest, approver.strip(), approved, reason)

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
            # Directory-name fallback lets stale/malformed files be found and rejected by
            # the base digest check, rather than being mistaken for a missing skill.
            if resolved.parent.name == skill_id or metadata_ids.get(resolved) == skill_id:
                matches.append(resolved)
        unique = list(dict.fromkeys(matches))
        if len(unique) != 1:
            raise GovernanceError(f"Expected exactly one skill target for {skill_id!r}; found {len(unique)}")
        return unique[0]

    @staticmethod
    def _atomic_write(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".skill-update-", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, target)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def apply(self, proposal: Proposal, approval: Approval) -> Path:
        if not approval.approved:
            raise GovernanceError("Proposal was not approved")
        if not approval.approver.strip() or approval.proposal_digest != proposal.proposal_digest:
            raise GovernanceError("Approval does not bind this exact proposal")
        if proposal.sealed().proposal_digest != proposal.proposal_digest:
            raise GovernanceError("Proposal digest is invalid")
        if not proposal.proposed_content.strip():
            raise GovernanceError("Proposed skill content must not be empty")
        if not self.audit.verify():
            raise GovernanceError("Audit ledger failed integrity verification; refusing skill update")

        target = self._find_target(proposal.skill_id)
        current = target.read_text(encoding="utf-8")
        if digest_text(current) != proposal.base_digest:
            raise GovernanceError("Stale proposal: base skill content has changed")

        self.archive_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        archive = self.archive_root / f"{proposal.skill_id}.{stamp}.SKILL.md"
        with archive.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(current)

        try:
            self._atomic_write(target, proposal.proposed_content)
            self.audit.append("skill_update_applied", {
                "skill_id": proposal.skill_id,
                "proposal_digest": proposal.proposal_digest,
                "approver": approval.approver,
                "archive": str(archive),
                "new_digest": digest_text(proposal.proposed_content),
            })
        except Exception:
            self._atomic_write(target, current)
            raise
        return target
