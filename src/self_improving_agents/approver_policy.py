"""Who may approve skill updates: an optional per-user list binding approval keys to approver names.

With no policy file the system runs as a documented single operator: any key that is not revoked may sign, and
the audit ledger records that. Once a policy exists, a key must be listed and the approver label must match it.
The file lives beside the revocation registry, outside the model's reach. It raises the bar but is not identity:
a process running as this user can edit it, and an HMAC key still proves possession only.
"""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import revocation
from .owner_only import owner_only_problem, restrict_to_current_user, save_owner_only

POLICY_NAME = "approvers.json"
SCHEMA = "approver-policy/1"
SINGLE_OPERATOR = "single_operator_default"
LISTED = "approver_policy"
_KEY_ID = re.compile(r"[0-9a-f]{64}")


class ApproverPolicyError(RuntimeError):
    pass


def policy_path() -> Path:
    return revocation.registry_dir() / POLICY_NAME


def _load(path: Path) -> list[dict]:
    problem = owner_only_problem(path.parent, directory=True) or owner_only_problem(path)
    if problem:
        raise ApproverPolicyError(f"Approver policy permissions are not owner-only: {problem}")
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ApproverPolicyError(f"Cannot read the approver policy {path}: {exc}") from exc
    approvers = document.get("approvers") if isinstance(document, dict) else None
    if (not isinstance(document, dict) or document.get("schema") != SCHEMA or not isinstance(approvers, list)
            or not all(isinstance(entry, dict) and isinstance(entry.get("key_id"), str)
                       and _KEY_ID.fullmatch(entry["key_id"]) and isinstance(entry.get("name"), str)
                       and entry["name"].strip() for entry in approvers)):
        raise ApproverPolicyError(f"Approver policy {path} is malformed; refusing to use it")
    return approvers


def authorize(key_id: str, approver: str) -> str:
    """How this key and approver label are authorized, or ApproverPolicyError if they are not."""
    path = policy_path()
    if not (path.exists() or path.is_symlink()):
        return SINGLE_OPERATOR
    if not any(entry["key_id"] == key_id and entry["name"] == approver for entry in _load(path)):
        raise ApproverPolicyError(f"Key {key_id[:12]}… with approver {approver!r} is not listed in the approver policy")
    return LISTED


def add_approver(key_id: str, name: str) -> dict:
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise ApproverPolicyError("key_id must be a full 64-character lowercase SHA-256 identifier")
    if not isinstance(name, str) or not name.strip():
        raise ApproverPolicyError("Approver name must be non-empty")
    path = policy_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not (path.exists() or path.is_symlink()):
            restrict_to_current_user(path.parent, directory=True)
        with revocation._locked(path.parent):
            approvers = _load(path) if path.exists() or path.is_symlink() else []
            if any(entry["key_id"] == key_id and entry["name"] == name.strip() for entry in approvers):
                return {"status": "already_listed", "key_id": key_id, "name": name.strip()}
            approvers.append({"key_id": key_id, "name": name.strip(),
                              "added_at": datetime.now(timezone.utc).isoformat()})
            save_owner_only(path, {"schema": SCHEMA, "approvers": approvers})
    except ApproverPolicyError:
        raise
    except Exception as exc:
        raise ApproverPolicyError(f"Could not update the approver policy {path}: {exc}") from exc
    return {"status": "approver_added", "key_id": key_id, "name": name.strip(), "path": str(path)}


def list_approvers() -> list[dict]:
    path = policy_path()
    return _load(path) if path.exists() or path.is_symlink() else []
