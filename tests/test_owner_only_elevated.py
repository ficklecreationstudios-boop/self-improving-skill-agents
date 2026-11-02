"""An elevated process's new files belong to Administrators (O:BA); the owner-only check must stay strict anyway."""
import json
import os
import re
import subprocess

import pytest

from self_improving_agents import owner_only, revocation
from self_improving_agents.owner_only import expand_local_administrator, own_as_current_user, owner_only_problem, sddl_problem

windows_only = pytest.mark.skipif(os.name != "nt", reason="Windows ownership behavior")
ME = "S-1-5-21-1-2-3-500"


def test_local_administrator_alias_compares_as_its_sid():
    sddl = expand_local_administrator("O:LAD:PAI(A;OICI;FA;;;LA)", ME)
    assert sddl == f"O:{ME}D:PAI(A;OICI;FA;;;{ME})"
    assert sddl_problem(sddl, ME) is None


@pytest.mark.parametrize("sddl", ["O:BAD:PAI(A;;FA;;;LA)", "O:LAD:PAI(A;;FA;;;LA)(A;;FR;;;WD)", "O:LAD:PAI(A;;FA;;;BA)"])
def test_expanding_the_alias_does_not_excuse_another_principal(sddl):
    assert sddl_problem(expand_local_administrator(sddl, ME), ME) is not None


def test_administrators_ownership_is_still_refused():
    assert "owner is BA" in sddl_problem(f"O:BAD:PAI(A;;FA;;;{ME})", ME)


@windows_only
def test_alias_assumption_holds_for_the_real_builtin_administrator(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("x")
    admin = owner_only._local_administrator_sid()
    assert admin.endswith("-500")
    subprocess.run(["icacls", str(target), "/grant", f"*{admin}:(R)"], capture_output=True, check=True)
    assert f";;;{admin})" in owner_only._windows_security_descriptor(target)


@windows_only
def test_owner_is_left_alone_when_already_the_current_user(tmp_path, monkeypatch):
    target = tmp_path / "file.txt"
    target.write_text("x")
    owner_only.restrict_to_current_user(target)  # a new file belongs to Administrators when elevated
    monkeypatch.setattr(owner_only.subprocess, "run", lambda *a, **k: pytest.fail("no icacls call was needed"))
    own_as_current_user(target)


@windows_only
def test_real_icacls_accepts_the_set_owner_call(tmp_path, monkeypatch):
    target = tmp_path / "file.txt"
    target.write_text("x")
    owner_only.restrict_to_current_user(target)
    calls = []
    run = subprocess.run
    monkeypatch.setattr(owner_only, "_windows_security_descriptor", lambda path: "O:BAD:")
    monkeypatch.setattr(owner_only.subprocess, "run", lambda cmd, **k: (calls.append(cmd), run(cmd, **k))[1])
    own_as_current_user(target)
    assert calls == [["icacls", str(target), "/setowner", f"*{owner_only.current_user_sid()}"]]
    monkeypatch.undo()
    assert owner_only_problem(target) is None


@windows_only
def test_restriction_sets_the_owner_after_granting_access(tmp_path, monkeypatch):
    """The owner change needs WRITE_OWNER, which the grant provides."""
    target = tmp_path / "file.txt"
    target.write_text("x")
    calls = []
    monkeypatch.setattr(owner_only.subprocess, "run", lambda cmd, **k: calls.append(cmd[2]))
    monkeypatch.setattr(owner_only, "_windows_security_descriptor", lambda path: "O:BAD:")
    owner_only.restrict_to_current_user(target)
    assert calls == ["/inheritance:r", "/setowner"]


def test_saving_takes_ownership_of_the_temp_file_before_checking_it(tmp_path, monkeypatch):
    events = []
    monkeypatch.setattr(revocation, "own_as_current_user", lambda path: events.append(("own", path.name)))
    monkeypatch.setattr(revocation, "owner_only_problem", lambda path, **_: events.append(("check", path.name)))
    revocation._store_unlocked(tmp_path / "registry.json", [])
    assert events[:2] == [("own", "registry.json.tmp"), ("check", "registry.json.tmp")]
    assert json.loads((tmp_path / "registry.json").read_text())["revocations"] == []


@pytest.mark.parametrize("failure", [subprocess.CalledProcessError(1, "icacls"), OSError("denied"), RuntimeError("no sid")])
def test_a_failed_owner_change_refuses_the_save_and_keeps_the_registry(tmp_path, monkeypatch, failure):
    path = tmp_path / "registry.json"
    path.write_text("original")

    def refuse(_):
        raise failure

    monkeypatch.setattr(revocation, "own_as_current_user", refuse)
    with pytest.raises(revocation.RevocationRegistryError, match="Could not safely update"):
        revocation._store_unlocked(path, [])
    assert path.read_text() == "original"


def test_an_owner_change_that_did_not_take_refuses_the_save(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text("original")
    monkeypatch.setattr(revocation, "own_as_current_user", lambda _: None)
    monkeypatch.setattr(revocation, "owner_only_problem", lambda _: "owner is BA, not the current user")
    with pytest.raises(revocation.RevocationRegistryError, match="not owner-only"):
        revocation._store_unlocked(path, [])
    assert path.read_text() == "original"


@windows_only
def test_registry_works_when_new_files_belong_to_administrators(tmp_path, monkeypatch):
    """Replays hosted CI run 41248211997: everything reads as O:BA until icacls really runs /setowner on it."""
    directory = tmp_path / "profile" / revocation.APP_DIRECTORY
    monkeypatch.setattr(revocation, "registry_dir", lambda: directory)
    real_descriptor = owner_only._windows_security_descriptor
    run = subprocess.run
    owned = set()

    def as_elevated(path):
        sddl = real_descriptor(path)
        return sddl if os.stat(path).st_ino in owned else re.sub(r"^O:[^D]*", "O:BA", sddl)

    def recording_run(cmd, **kwargs):
        result = run(cmd, **kwargs)
        if "/setowner" in cmd:
            owned.add(os.stat(cmd[1]).st_ino)
        return result

    monkeypatch.setattr(owner_only, "_windows_security_descriptor", as_elevated)
    monkeypatch.setattr(owner_only.subprocess, "run", recording_run)
    revocation.init_registry()
    path = revocation.registry_path()
    with revocation._locked(path.parent):
        revocation._store_unlocked(path, [])
    assert owner_only_problem(path.parent, directory=True) is None
    assert owner_only_problem(path) is None
