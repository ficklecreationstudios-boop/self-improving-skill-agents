import pytest
from self_improving_agents.approval_auth import sign_approval, ApprovalSignatureError
from self_improving_agents.models import Approval


def test_signing_requires_named_approver_and_reason():
    key = b"approval-test-key-32-bytes-or-more-long"
    with pytest.raises(ApprovalSignatureError, match="Approver"):
        sign_approval(Approval("a" * 64, " ", True, "reviewed"), key)
    with pytest.raises(ApprovalSignatureError, match="reason"):
        sign_approval(Approval("a" * 64, "reviewer", True, " "), key)
