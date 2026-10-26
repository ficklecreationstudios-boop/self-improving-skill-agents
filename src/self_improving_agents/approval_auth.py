"""Shared-secret signed approvals with explicit key identity.

HMAC proves possession of a secret key, not a real-world identity. Store keys outside
the repository and restrict access using the host OS. Revocation state is recorded in
the hash-chained audit ledger and is checked before signing or applying approvals.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import re
from .models import Approval


class ApprovalSignatureError(ValueError):
    pass


def validate_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ApprovalSignatureError("Approval key must contain at least 32 random bytes")


def key_identifier(key: bytes) -> str:
    validate_key(key)
    return hashlib.sha256(key).hexdigest()


def approval_message(approval: Approval) -> bytes:
    payload = json.dumps(approval.payload(), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return b"self-improving-skill-agents-approval-v2\0" + payload


def sign_approval(approval: Approval, key: bytes) -> Approval:
    validate_key(key)
    if approval.approved is not True:
        raise ApprovalSignatureError("Only explicitly approved records can be signed")
    if not approval.approver.strip():
        raise ApprovalSignatureError("Approver label must be non-empty")
    if not approval.proposal_digest or not approval.reason.strip():
        raise ApprovalSignatureError("Proposal digest and approval reason must be non-empty")
    identified = Approval(approval.proposal_digest, approval.approver, approval.approved,
                          approval.reason, "", key_identifier(key))
    signature = hmac.new(key, approval_message(identified), hashlib.sha256).hexdigest()
    return Approval(identified.proposal_digest, identified.approver, identified.approved,
                    identified.reason, signature, identified.key_id)


def verify_approval(approval: Approval, key: bytes) -> bool:
    validate_key(key)
    if (approval.approved is not True or not approval.approver.strip()
            or not approval.reason.strip() or not approval.signature
            or not re.fullmatch(r"[0-9a-f]{64}", approval.key_id)
            or not hmac.compare_digest(approval.key_id, key_identifier(key))):
        return False
    unsigned = Approval(approval.proposal_digest, approval.approver, approval.approved,
                        approval.reason, "", approval.key_id)
    expected = hmac.new(key, approval_message(unsigned), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, approval.signature)
