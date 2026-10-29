from pathlib import Path

from self_improving_agents.capabilities import CapabilityRegistry


def test_search_text_stops_enumerating_at_entry_limit(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sample = workspace / "sample.txt"
    sample.write_text("x", encoding="utf-8")

    registry = CapabilityRegistry(workspace)
    yielded = 0

    def many_paths(self, pattern):
        nonlocal yielded
        assert self == registry.workspace
        for _ in range(5000):
            yielded += 1
            yield sample

    monkeypatch.setattr(Path, "rglob", many_paths)

    result = registry.invoke("search_text", {"query": "not-present"})

    assert result["ok"] is False
    assert "limit" in result["error"].lower()
    assert yielded <= 2001, (
        "Search enumerated the entire path iterator before enforcing its bound: "
        "{} entries".format(yielded)
    )


def test_search_text_counts_oversized_candidates_toward_limit(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sample = workspace / "oversized.txt"
    sample.write_text("too large", encoding="utf-8")

    registry = CapabilityRegistry(workspace, max_file_bytes=1)

    def many_oversized_paths(self, pattern):
        assert self == registry.workspace
        for _ in range(2001):
            yield sample

    monkeypatch.setattr(Path, "rglob", many_oversized_paths)

    result = registry.invoke("search_text", {"query": "not-present"})

    assert result["ok"] is False, (
        "Oversized candidates bypassed the search work-count limit"
    )
    assert "limit" in result["error"].lower()
