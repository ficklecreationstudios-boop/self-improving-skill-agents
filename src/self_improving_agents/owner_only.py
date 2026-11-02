"""Files and directories that only the current user can open: restrict them, and verify it."""
from __future__ import annotations
import functools
import os
import re
import stat
import subprocess
from pathlib import Path

_OWNER = re.compile(r"O:(S-1-[0-9-]+|[A-Z]{2})")


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
    _replace_windows_dacl(path, f"D:P(A;{'OICI' if directory else ''};FA;;;{current_user_sid()})")
    own_as_current_user(path)


def _replace_windows_dacl(path: Path, sddl: str) -> None:
    """Replace path's whole access-control list. icacls /inheritance:r can leave entries not marked as inherited."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    from_string = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    from_string.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                            ctypes.POINTER(wintypes.ULONG)]
    from_string.restype = wintypes.BOOL
    get_dacl = advapi32.GetSecurityDescriptorDacl
    get_dacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p),
                         ctypes.POINTER(wintypes.BOOL)]
    get_dacl.restype = wintypes.BOOL
    set_security = advapi32.SetNamedSecurityInfoW
    set_security.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p]
    set_security.restype = wintypes.DWORD
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    if not from_string(sddl, 1, ctypes.byref(descriptor), None):
        raise OSError(ctypes.get_last_error(), "cannot build the access-control list", str(path))
    try:
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not get_dacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)) or not present:
            raise OSError(ctypes.get_last_error(), "cannot read the new access-control list", str(path))
        info = 0x4 | 0x80000000  # DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION
        error = set_security(str(path), 1, info, None, None, dacl, None)  # 1 = SE_FILE_OBJECT
        if error:
            raise OSError(error, "cannot set the access-control list", str(path))
    finally:
        kernel32.LocalFree(descriptor)


def own_as_current_user(path: Path) -> None:
    """Make the current user the owner of path; an elevated process's new files belong to Administrators."""
    if os.name != "nt":
        return
    owner = _OWNER.match(_windows_security_descriptor(path))
    if not owner or owner.group(1) != current_user_sid():
        subprocess.run(["icacls", str(path), "/setowner", f"*{current_user_sid()}"],
                       capture_output=True, text=True, timeout=30, check=True)


@functools.lru_cache(maxsize=1)
def _local_administrator_sid() -> str:
    """The SID that the SDDL alias LA stands for on this computer."""
    import ctypes
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    binary = ctypes.c_void_p()
    if not advapi32.ConvertStringSidToSidW("LA", ctypes.byref(binary)):
        raise OSError(ctypes.get_last_error(), "cannot resolve the local administrator SID")
    try:
        text = wintypes.LPWSTR()
        if not advapi32.ConvertSidToStringSidW(binary, ctypes.byref(text)):
            raise OSError(ctypes.get_last_error(), "cannot convert the local administrator SID")
        try:
            return text.value or ""
        finally:
            kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    finally:
        kernel32.LocalFree(binary)


def expand_local_administrator(sddl: str, sid: str) -> str:
    """Windows writes the built-in Administrator's SID as LA in SDDL; put the SID back so it compares by SID."""
    return re.sub(r"(?<=O:)LA(?=D:|G:|$)|(?<=;)LA(?=\))", sid, sddl)


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
        sddl = text.value or ""
    finally:
        kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
    return expand_local_administrator(sddl, _local_administrator_sid()) if "LA" in sddl else sddl


def sddl_problem(sddl: str, sid: str) -> str | None:
    """Why an owner+DACL SDDL string is not owner-only for sid, or None if it is."""
    owner = _OWNER.match(sddl)
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
