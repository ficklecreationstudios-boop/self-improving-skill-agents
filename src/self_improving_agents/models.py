from __future__ import annotations
from dataclasses import dataclass, asdict, replace
from hashlib import sha256
import json
from typing import Any

def digest_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()

def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return digest_text(raw)

@dataclass(frozen=True)
class Task:
    text: str
    domain: str = "general"
    task_id: str = ""

@dataclass(frozen=True)
class Skill:
    skill_id: str
    name: str
    domain: str
    tags: tuple[str, ...]
    path: str
    content: str = ""

@dataclass(frozen=True)
class Review:
    task_digest: str
    output_digest: str
    verdict: str
    notes: str

@dataclass(frozen=True)
class Proposal:
    skill_id: str
    base_digest: str
    proposed_content: str
    rationale: str
    proposal_digest: str = ""
    def payload(self) -> dict[str, Any]:
        return {"skill_id": self.skill_id, "base_digest": self.base_digest, "proposed_content": self.proposed_content, "rationale": self.rationale}
    def sealed(self) -> "Proposal":
        return replace(self, proposal_digest=canonical_digest(self.payload()))

@dataclass(frozen=True)
class Approval:
    proposal_digest: str
    approver: str
    approved: bool
    reason: str = ""
    signature: str = ""
    def payload(self) -> dict[str, Any]:
        return {"proposal_digest": self.proposal_digest, "approver": self.approver,
                "approved": self.approved, "reason": self.reason}
