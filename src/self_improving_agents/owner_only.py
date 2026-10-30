"""Files and directories that only the current user can open: restrict them, and verify it."""
from __future__ import annotations
import functools
import os
import re
import stat
import subprocess
from pathlib import Path


@functools.lru_cache(maxsize=1)
def current_user_sid() -> str:
    who = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True,
                         timeout=30, check=True).stdout.strip()
    sid = who.rsplit(",", 1)[-1].strip().strip('"')
    if not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise RuntimeError(f"could not determine the current user's SID from {who!r}")
    return sid


def restrict_to_current_user(path: Path, *, directory: bool = False) -> None:
    """Leave only the current user with access: mode 0600/0700 on POSIX, a single owner ACE on Windows."""
    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)
        return
    grant = f"*{current_user_sid()}:(OI)(CI)(F)" if directory else f"*{current_user_sid()}:(F)"
    subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", grant],
                   capture_output=True, text=True, timeout=30, check=True)


def _windows_security_descriptor(path: Path) -> str:
    """Owner and DACL of path as an SDDL string, read in-process (no localized tool output)."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_security = advapi32.GetFileSecurityW
    get_security.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD)]
    get_security.restype = wintypes.BOOL
    to_string = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
    to_string.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                          ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.ULONG)]
    to_string.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    info = 0x1 | 0x4  # OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
    needed = wintypes.DWORD(0)
    get_security(str(path), info, None, 0, ctypes.byref(needed))
    if not needed.value:
        raise OSError(ctypes.get_last_error(), "cannot read the security descriptor", str(path))
    buffer = ctypes.create_string_buffer(needed.value)
    if not get_security(str(path), info, buffer, needed.value, ctypes.byref(needed)):
        raise OSError(ctypes.get_last_error(), "cannot read the security descriptor", str(path))
    text = wintypes.LPWSTR()
    if not to_string(buffer, 1, info, ctypes.byref(text), None):
        raise OSError(ctypes.get_last_error(), "cannot convert the security descriptor", str(path))
    try:
        return text.value or ""
    finally:
        kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def sddl_problem(sddl: str, sid: str) -> str | None:
    """Why an owner+DACL SDDL string is not owner-only for sid, or None if it is."""
    owner = re.match(r"O:(S-1-[0-9-]+|[A-Z]{2})", sddl)
    if not owner or owner.group(1) != sid:
        return f"owner is {owner.group(1) if owner else 'unknown'}, not the current user"
    dacl = re.search(r"D:([A-Z_]*)((?:\([^)]*\))*)", sddl)
    if not dacl:
        return "it has no access-control list"
    aces = re.findall(r"\(([^)]*)\)", dacl.group(2))
    if not aces:
        return "its access-control list has no entries"
    for ace in aces:
        fields = ace.split(";")
        if len(fields) < 6 or fields[0] != "A" or fields[5] != sid:
            return f"it grants access to another principal ({ace})"
    return None


def owner_only_problem(path: Path, *, directory: bool = False) -> str | None:
    """Why path is not a plain file (or directory) that only the current user can open; None if it is."""
    try:
        info = os.lstat(path)
    except OSError as exc:
        return f"cannot inspect {path}: {exc}"
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if not expected(info.st_mode):
        return f"{path} is not a {'directory' if directory else 'regular file'}"
    if os.name != "nt":
        if info.st_uid != os.getuid():
            return f"{path} is not owned by the current user"
        if info.st_mode & 0o077:
            return f"{path} is accessible to other users (mode {stat.S_IMODE(info.st_mode):o})"
        return None
    if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return f"{path} is a link or reparse point"
    try:
        problem = sddl_problem(_windows_security_descriptor(path), current_user_sid())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        return f"cannot verify the permissions of {path}: {exc}"
    return f"{path}: {problem}" if problem else None
