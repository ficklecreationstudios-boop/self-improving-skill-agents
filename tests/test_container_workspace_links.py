"""Junctions and symlinks inside the workspace must not expose files outside it.

Covers the in-process registry and the real container path. How Docker Desktop presents a
Windows reparse point inside a bind mount is not assumed; the requirement is only that
outside content never reaches a tool result, a later prompt, or the final answer.
"""
import os

import pytest

from self_improving_agents import container_capabilities as sandbox
from self_improving_agents.capabilities import CapabilityRegistry
from test_forced_attack_enforcement import (  # noqa: F401 (fixtures)
    CANARY, _layout, _run_attack, host_reads, real_container_root,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows junctions and symlinks")


def _outside_dir(root):
    outside = root / "outside-dir"
    outside.mkdir()
    (outside / "canary.txt").write_text(CANARY, encoding="utf-8")
    return outside


def _make_link(kind, link, target):
    if kind == "junction":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"Symlink creation unavailable on this runner: {exc}")


def _attack_calls():
    return [("read_text_file", {"path": "escape/canary.txt"}), ("search_text", {"query": "CANARY_SECRET"})]


def _assert_no_outside_content(result, adapter):
    assert result.stop_reason == "final_answer"
    read, search = result.tool_calls
    assert read["result"]["ok"] is False, read
    assert search["result"]["ok"] is True and search["result"]["result"]["matches"] == [], search
    assert CANARY not in result.output
    assert all(CANARY not in prompt for prompt in adapter.prompts)


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_in_process_workspace_link_cannot_expose_outside_dir(tmp_path, host_reads, kind):
    workspace, _, _ = _layout(tmp_path)
    outside = _outside_dir(tmp_path)
    _make_link(kind, workspace / "escape", outside)

    result, adapter, _ = _run_attack(CapabilityRegistry(workspace), tmp_path, *_attack_calls())

    _assert_no_outside_content(result, adapter)
    assert (outside / "canary.txt").resolve() not in host_reads


@pytest.mark.parametrize("kind", ["junction", "symlink"])
def test_real_container_workspace_link_cannot_expose_outside_dir(real_container_root, kind):
    workspace, _, _ = _layout(real_container_root)
    outside = _outside_dir(real_container_root)
    _make_link(kind, workspace / "escape", outside)
    registry = sandbox.ContainerCapabilityRegistry(workspace, timeout_seconds=20)

    result, adapter, _ = _run_attack(registry, real_container_root, *_attack_calls())

    _assert_no_outside_content(result, adapter)
