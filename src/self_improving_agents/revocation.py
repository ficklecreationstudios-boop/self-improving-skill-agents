"""Per-user approval-key revocation registry, independent of any audit ledger.

A revocation recorded only in one audit ledger was invisible to a different ledger. This
registry lives at a fixed place in the current user's profile (no option or environment
variable selects it), only that user can open it, and it is checked whenever a key signs or
applies an approval. It fails closed: a missing, unreadable, corrupt or over-permissive
registry stops signing and applying, and it is never created or reset implicitly.

The digest detects accidental corruption and partial edits; it is not a signature, so it
does not stop someone who can already write files as this user.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from .file_lock import exclusive_lock
from .owner_only import owner_only_problem, restrict_to_current_user

APP_DIRECTORY = "self-improving-skill-agents"
REGISTRY_NAME = "approval-key-revocations.json"
SCHEMA = 1
MAX_REGISTRY_BYTES = 1_000_000
_KEY_ID = re.compile(r"[0-9a-f]{64}")
_FOLDERID_LOCAL_APPDATA = "F1B32785-6FBA-4FCF-9D55-7B8E7F157091"


class RevocationRegistryError(RuntimeError):
    """The revocation registry is missing, unsafe, corrupt, or could not be updated."""


def _known_local_appdata() -> Path:
    """The profile's local application-data folder, from the OS rather than environment variables."""
    if os.name != "nt":
        import pwd
        return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".local" / "state"
    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    folder_id = GUID.from_buffer_copy(uuid.UUID(_FOLDERID_LOCAL_APPDATA).bytes_le)
    shell32, ole32 = ctypes.WinDLL("shell32"), ctypes.WinDLL("ole32")
    shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
                                             ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    found = ctypes.c_void_p()
    result = shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, None, ctypes.byref(found))
    try:
        if result != 0 or not found.value:
            raise RevocationRegistryError(f"Cannot locate the profile's LocalAppData folder (HRESULT {result})")
        return Path(ctypes.wstring_at(found.value))
    finally:
        ole32.CoTaskMemFree(found)


def registry_dir() -> Path:
    return _known_local_appdata() / APP_DIRECTORY


def registry_path() -> Path:
    return registry_dir() / REGISTRY_NAME


def _missing(path: Path) -> RevocationRegistryError:
    return RevocationRegistryError(
        f"Approval-key revocation registry is missing at {path}; signing and applying are refused. "
        "Create it once with 'skill-agents init-revocation-registry' (use --import-audit to carry over "
        "revocations from existing audit ledgers). It is never recreated automatically.")


@contextmanager
def _locked(directory: Path):
    """Serialize registry reads and writes across processes on Windows and POSIX."""
    with exclusive_lock(directory / (REGISTRY_NAME + ".lock")):
        yield


def _digest(revocations: list[dict]) -> str:
    return sha256(json.dumps(revocations, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")).hexdigest()


def _check_access(path: Path) -> None:
    problem = owner_only_problem(path.parent, directory=True) or owner_only_problem(path)
    if problem:
        raise RevocationRegistryError(f"Revocation registry permissions are not owner-only: {problem}")


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _load_unlocked(path: Path) -> list[dict]:
    if not path.is_file():
        raise _missing(path)
    _check_access(path)
    try:
        raw = _read_bytes(path)
        if len(raw) > MAX_REGISTRY_BYTES:
            raise ValueError(f"registry exceeds {MAX_REGISTRY_BYTES} bytes")
        document = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RevocationRegistryError(f"Revocation registry {path} is unreadable or corrupt: {exc}") from exc
    if (not isinstance(document, dict) or set(document) != {"schema", "revocations", "digest"}
            or document["schema"] != SCHEMA or not isinstance(document["revocations"], list)):
        raise RevocationRegistryError(f"Revocation registry {path} has an invalid structure")
    revocations, seen = document["revocations"], set()
    for item in revocations:
        if (not isinstance(item, dict) or set(item) != {"key_id", "reason", "revoked_at"}
                or not isinstance(item["key_id"], str) or not _KEY_ID.fullmatch(item["key_id"])
                or not isinstance(item["reason"], str) or not item["reason"].strip()
                or not isinstance(item["revoked_at"], str) or item["key_id"] in seen):
            raise RevocationRegistryError(f"Revocation registry {path} contains an invalid entry")
        seen.add(item["key_id"])
    if document["digest"] != _digest(revocations):
        raise RevocationRegistryError(f"Revocation registry {path} failed its digest check")
    return revocations


def _store_unlocked(path: Path, revocations: list[dict]) -> None:
    document = {"schema": SCHEMA, "revocations": revocations, "digest": _digest(revocations)}
    data = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.unlink(missing_ok=True)
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        problem = owner_only_problem(temp)
        if problem:
            raise RevocationRegistryError(f"Refusing to save a revocation registry that is not owner-only: {problem}")
        os.replace(temp, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except OSError as exc:
        raise RevocationRegistryError(f"Could not safely update the revocation registry {path}: {exc}") from exc
    finally:
        temp.unlink(missing_ok=True)
    _check_access(path)


def revoked_key_ids() -> frozenset[str]:
    path = registry_path()
    if not path.is_file():
        raise _missing(path)
    with _locked(path.parent):
        return frozenset(item["key_id"] for item in _load_unlocked(path))


def add_revocation(key_id: str, reason: str) -> bool:
    """Record a revoked key ID. Returns False if it was already recorded."""
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise RevocationRegistryError("key_id must be a full 64-character lowercase SHA-256 identifier")
    if not isinstance(reason, str) or not reason.strip():
        raise RevocationRegistryError("Revocation reason must be non-empty")
    path = registry_path()
    if not path.is_file():
        raise _missing(path)
    with _locked(path.parent):
        revocations = _load_unlocked(path)
        if any(item["key_id"] == key_id for item in revocations):
            return False
        revocations.append({"key_id": key_id, "reason": reason.strip(),
                            "revoked_at": datetime.now(timezone.utc).isoformat()})
        _store_unlocked(path, revocations)
        return True


def init_registry(imported: list[tuple[str, str]] = ()) -> dict:
    """Create the registry once, optionally seeded with (key_id, reason) pairs. Never overwrites."""
    path = registry_path()
    if path.exists() or path.is_symlink():
        raise RevocationRegistryError(f"Revocation registry already exists at {path}; it is never recreated or reset")
    revocations, seen = [], set()
    for key_id, reason in imported:
        if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id) or not str(reason).strip():
            raise RevocationRegistryError(f"Cannot import invalid revocation for key {key_id!r}")
        if key_id not in seen:
            seen.add(key_id)
            revocations.append({"key_id": key_id, "reason": str(reason).strip(),
                                "revoked_at": datetime.now(timezone.utc).isoformat()})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        restrict_to_current_user(path.parent, directory=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise RevocationRegistryError(f"Could not create an owner-only registry folder {path.parent}: {exc}") from exc
    problem = owner_only_problem(path.parent, directory=True)
    if problem:
        raise RevocationRegistryError(f"Registry folder is not owner-only after restriction: {problem}")
    with _locked(path.parent):
        if path.exists() or path.is_symlink():
            raise RevocationRegistryError(f"Revocation registry already exists at {path}; it is never recreated or reset")
        _store_unlocked(path, revocations)
    return {"status": "registry_created", "path": str(path), "revoked_key_count": len(revocations)}
