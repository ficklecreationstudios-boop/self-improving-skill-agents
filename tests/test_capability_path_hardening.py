import pytest

from self_improving_agents.capabilities import CapabilityRegistry


def _make_symlink_or_skip(link, target, *, is_directory=False):
    try:
        link.symlink_to(target, target_is_directory=is_directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip("Symlink creation unavailable on this runner: {}".format(exc))


def test_search_text_ignores_symlink_to_outside_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    outside = tmp_path / "outside.txt"
    outside.write_text("D8_OUTSIDE_FILE_CANARY", encoding="utf-8")
    _make_symlink_or_skip(workspace / "linked.txt", outside)

    result = CapabilityRegistry(workspace).invoke(
        "search_text", {"query": "D8_OUTSIDE_FILE_CANARY"}
    )

    assert result["ok"] is True
    assert result["result"]["matches"] == []


def test_search_text_ignores_symlink_to_outside_directory(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text(
        "D8_OUTSIDE_DIRECTORY_CANARY", encoding="utf-8"
    )
    _make_symlink_or_skip(
        workspace / "external.txt", outside, is_directory=True
    )

    result = CapabilityRegistry(workspace).invoke(
        "search_text", {"query": "D8_OUTSIDE_DIRECTORY_CANARY"}
    )

    assert result["ok"] is True
    assert result["result"]["matches"] == []


def test_search_text_handles_cyclic_symlink_without_crashing(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    cycle = workspace / "cycle.txt"
    _make_symlink_or_skip(cycle, cycle)

    result = CapabilityRegistry(workspace).invoke(
        "search_text", {"query": "D8_CYCLE_CANARY"}
    )

    assert result["ok"] is True
    assert result["result"]["matches"] == []
