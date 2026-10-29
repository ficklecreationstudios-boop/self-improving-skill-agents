import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from self_improving_agents.container_capabilities import (
    ContainerCapabilityRegistry,
    PINNED_IMAGE,
)


def test_real_container_reads_searches_and_rejects_mount_escape():
    try:
        info = subprocess.run(
            ["docker.exe", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if info.returncode != 0:
            pytest.skip("Docker daemon is unavailable")

        image = subprocess.run(
            ["docker.exe", "image", "inspect", PINNED_IMAGE],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if image.returncode != 0:
            pytest.skip("Pinned sandbox image is unavailable")
    except (OSError, subprocess.SubprocessError):
        pytest.skip("Docker CLI or daemon is unavailable")

    root_value = os.environ.get("D8_CONTAINER_TEST_ROOT")
    if not root_value:
        pytest.fail("D8_CONTAINER_TEST_ROOT must specify the D: test workspace root")

    root = Path(root_value).resolve()
    if not root.is_dir() or root.drive.upper() != "D:":
        pytest.fail("Container integration workspace must be an existing D: directory")

    # Use a normal directory so it inherits the parent Windows ACL.
    workspace = root / ("d8-container-workspace-" + uuid.uuid4().hex[:16])
    workspace.mkdir()

    try:
        (workspace / "notes.md").write_text(
            "D8_CONTAINER_WORKSPACE_CANARY\n",
            encoding="utf-8",
        )

        registry = ContainerCapabilityRegistry(workspace, timeout_seconds=8)

        read_result = registry.invoke(
            "read_text_file", {"path": "notes.md"}
        )
        assert read_result["ok"] is True, read_result
        assert read_result["result"]["path"] == "notes.md"
        assert "D8_CONTAINER_WORKSPACE_CANARY" in read_result["result"]["content"]

        search_result = registry.invoke(
            "search_text", {"query": "D8_CONTAINER_WORKSPACE_CANARY"}
        )
        assert search_result["ok"] is True, search_result
        assert any(
            match["path"] == "notes.md"
            and "D8_CONTAINER_WORKSPACE_CANARY" in match["text"]
            for match in search_result["result"]["matches"]
        ), search_result

        # The package is mounted separately at /opt/package. This request
        # attempts to read that mounted file via a path outside /workspace.
        escape_result = registry.invoke(
            "read_text_file",
            {"path": "../opt/package/self_improving_agents/capabilities.py"},
        )
        assert escape_result["ok"] is False, escape_result
        assert "escapes configured workspace" in escape_result["error"].lower()
        assert "class CapabilityRegistry" not in str(escape_result)

    finally:
        shutil.rmtree(workspace, ignore_errors=True)
