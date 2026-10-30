import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from self_improving_agents import revocation


@pytest.fixture(scope="session")
def _session_revocation_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("revocation-registry") / revocation.APP_DIRECTORY


@pytest.fixture(autouse=True)
def isolated_revocation_registry(_session_revocation_dir, monkeypatch):
    """Point the per-user revocation registry at a test folder and start every test with it empty.

    Tests must never read or write the real registry in the user's profile.
    """
    monkeypatch.setattr(revocation, "registry_dir", lambda: _session_revocation_dir)
    path = revocation.registry_path()
    if path.is_file():
        with revocation._locked(path.parent):
            revocation._store_unlocked(path, [])
    else:
        revocation.init_registry()
    return path
