"""Shared-secret signed approvals.

HMAC proves possession of a secret key, not a real-world identity. Store the key
outside the repository and restrict its file permissions using the host OS.
"""
from __future__ import annotations
import hashlib
import hmac
import json
from .models import Approval


class ApprovalSignatureError(ValueError):
    pass


def validate_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ApprovalSignatureError("Approval key must contain at least 32 random bytes")


def approval_message(approval: Approval) -> bytes:
    payload = json.dumps(approval.payload(), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return b"self-improving-skill-agents-approval-v1\0" + payload


def sign_approval(approval: Approval, key: bytes) -> Approval:
    validate_key(key)
    if not approval.approved:
        raise ApprovalSignatureError("Only explicitly approved records can be signed")
    signature = hmac.new(key, approval_message(approval), hashlib.sha256).hexdigest()
    return Approval(approval.proposal_digest, approval.approver, approval.approved,
                    approval.reason, signature)


def verify_approval(approval: Approval, key: bytes) -> bool:
    validate_key(key)
    if not approval.approved or not approval.approver.strip() or not approval.signature:
        return False
    expected = hmac.new(key, approval_message(Approval(
        approval.proposal_digest, approval.approver, approval.approved, approval.reason
    )), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, approval.signature)
