"""Approval-bound skill updates with archived prior versions."""
from pathlib import Path
from datetime import datetime, timezone
import re
from ..models import Proposal, Approval, digest_text
from ..audit import AuditLedger

class GovernanceError(RuntimeError): pass

class Governance:
    def __init__(self, skill_root: str | Path, archive_root: str | Path, audit: AuditLedger):
        self.skill_root, self.archive_root, self.audit = Path(skill_root).resolve(), Path(archive_root).resolve(), audit
    def issue_approval(self, proposal: Proposal, approver: str, approved: bool, reason: str = "") -> Approval:
        if not approver.strip(): raise GovernanceError("Approver identity must be non-empty")
        return Approval(proposal.proposal_digest, approver.strip(), approved, reason)
    def apply(self, proposal: Proposal, approval: Approval) -> Path:
        if not approval.approved: raise GovernanceError("Proposal was not approved")
        if not approval.approver.strip() or approval.proposal_digest != proposal.proposal_digest: raise GovernanceError("Approval does not bind this exact proposal")
        if proposal.sealed().proposal_digest != proposal.proposal_digest: raise GovernanceError("Proposal digest is invalid")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", proposal.skill_id): raise GovernanceError("Unsafe skill id")
        target = next((p.resolve() for p in self.skill_root.rglob("SKILL.md") if p.parent.name == proposal.skill_id), None)
        if target is None or self.skill_root not in target.parents: raise GovernanceError("Skill target not found under skill root")
        current = target.read_text(encoding="utf-8")
        if digest_text(current) != proposal.base_digest: raise GovernanceError("Stale proposal: base skill content has changed")
        self.archive_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        archive = self.archive_root / f"{proposal.skill_id}.{stamp}.SKILL.md"
        archive.write_text(current, encoding="utf-8")
        target.write_text(proposal.proposed_content, encoding="utf-8")
        self.audit.append("skill_update_applied", {"skill_id": proposal.skill_id, "proposal_digest": proposal.proposal_digest, "approver": approval.approver, "archive": str(archive), "new_digest": digest_text(proposal.proposed_content)})
        return target
