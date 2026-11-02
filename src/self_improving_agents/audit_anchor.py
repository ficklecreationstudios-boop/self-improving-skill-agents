"""Remember a ledger's fingerprint outside the ledger, so a full rewrite or truncation can be noticed.

The hash chain catches edits, but anyone able to write the file could rebuild a fresh, valid chain, because nothing
outside it remembers the last hash. An anchor records (seq, event_hash) in the per-user folder; verify-audit then
requires that event to still be there. A process running as this user can edit both files, so the printed hash
should also be kept somewhere else, and can be checked with verify-audit --anchor-seq and --anchor-hash.
"""
from __future__ import annotations
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import revocation
from .audit import AuditLedger
from .owner_only import owner_only_problem, restrict_to_current_user, save_owner_only

ANCHORS_NAME = "audit-anchors.json"
SCHEMA = "audit-anchors/1"
_HASH = re.compile(r"[0-9a-f]{64}")


class AuditAnchorError(RuntimeError):
    pass


def anchors_path() -> Path:
    return revocation.registry_dir() / ANCHORS_NAME


def _ledger_key(ledger_path: str | Path) -> str:
    return os.path.normcase(str(Path(ledger_path).resolve()))


def _valid(entry) -> bool:
    return (isinstance(entry, dict) and isinstance(entry.get("ledger"), str) and type(entry.get("seq")) is int
            and entry["seq"] >= 1 and isinstance(entry.get("event_hash"), str)
            and _HASH.fullmatch(entry["event_hash"]) is not None)


def _load(path: Path) -> list[dict]:
    problem = owner_only_problem(path.parent, directory=True) or owner_only_problem(path)
    if problem:
        raise AuditAnchorError(f"Audit anchor permissions are not owner-only: {problem}")
    try:
        document = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise AuditAnchorError(f"Cannot read the audit anchors {path}: {exc}") from exc
    anchors = document.get("anchors") if isinstance(document, dict) else None
    if (not isinstance(document, dict) or document.get("schema") != SCHEMA or not isinstance(anchors, list)
            or not all(_valid(entry) for entry in anchors)):
        raise AuditAnchorError(f"Audit anchors {path} are malformed; refusing to use them")
    return anchors


def record_anchor(ledger_path: str | Path) -> dict:
    """Write down the ledger's current last event. Refuses a ledger that does not verify."""
    ledger = AuditLedger(ledger_path)
    if not ledger.verify():
        raise AuditAnchorError("Audit ledger failed integrity verification; refusing to anchor it")
    events = ledger._events()
    if not events:
        raise AuditAnchorError("Audit ledger has no events to anchor")
    problems = anchor_problems(ledger_path)
    if problems:
        raise AuditAnchorError("; ".join(problems))
    entry = {"ledger": _ledger_key(ledger_path), "seq": events[-1]["seq"], "event_hash": events[-1]["event_hash"],
             "anchored_at": datetime.now(timezone.utc).isoformat()}
    path = anchors_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not (path.exists() or path.is_symlink()):
            restrict_to_current_user(path.parent, directory=True)
        with revocation._locked(path.parent):
            anchors = _load(path) if path.exists() or path.is_symlink() else []
            save_owner_only(path, {"schema": SCHEMA, "anchors": anchors + [entry]})
    except AuditAnchorError:
        raise
    except Exception as exc:
        raise AuditAnchorError(f"Could not save the audit anchor {path}: {exc}") from exc
    return entry


def check_event(events: list[dict], seq: int, event_hash: str) -> str | None:
    """Why the ledger no longer holds this anchored event, or None if it does."""
    if seq < 1 or seq > len(events):
        return f"anchored event {seq} is missing; the ledger has {len(events)} events (truncated or replaced)"
    if events[seq - 1].get("event_hash") != event_hash:
        return f"event {seq} does not match its anchored hash (the ledger was rewritten)"
    return None


def anchor_problems(ledger_path: str | Path) -> list[str]:
    """Every anchor recorded for this ledger path must still hold. No anchors means nothing to check."""
    path = anchors_path()
    if not (path.exists() or path.is_symlink()):
        return []
    key = _ledger_key(ledger_path)
    mine = [entry for entry in _load(path) if entry["ledger"] == key]
    if not mine:
        return []
    events = AuditLedger(ledger_path)._events()
    return [problem for problem in (check_event(events, e["seq"], e["event_hash"]) for e in mine) if problem]
