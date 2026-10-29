"""A missing sandbox image must fail closed without the Docker daemon attempting a pull.

Uses an all-zero digest that cannot exist locally, so no real image is removed or changed.
Docker prints "Unable to find image ... locally" immediately before every pull attempt,
online or offline; its absence shows no pull was attempted.
"""
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from self_improving_agents import container_capabilities as sandbox

MISSING_IMAGE = "python@sha256:" + "0" * 64


def test_missing_image_fails_closed_without_pull(monkeypatch):
    try:
        info = subprocess.run(["docker.exe", "info", "--format", "{{.ServerVersion}}"],
                              capture_output=True, timeout=10, check=False)
        if info.returncode != 0:
            pytest.skip("Docker daemon is unavailable")
        present = subprocess.run(["docker.exe", "image", "inspect", MISSING_IMAGE],
                                 capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("Docker CLI or daemon is unavailable")
    if present.returncode == 0:
        pytest.fail("The all-zero test digest unexpectedly exists locally")

    root_value = os.environ.get("D8_CONTAINER_TEST_ROOT")
    if not root_value:
        pytest.fail("D8_CONTAINER_TEST_ROOT must specify an accessible D: directory")
    root = Path(root_value).resolve()
    if not root.is_dir() or root.drive.upper() != "D:":
        pytest.fail("Missing-image test workspace root must be an existing D: directory")

    workspace = root / ("d8-missing-image-" + uuid.uuid4().hex[:16])
    workspace.mkdir()
    try:
        monkeypatch.setattr(sandbox, "PINNED_IMAGE", MISSING_IMAGE)
        registry = sandbox.ContainerCapabilityRegistry(workspace, image=MISSING_IMAGE, timeout_seconds=20)

        started = time.monotonic()
        result = registry.invoke("calculator", {"expression": "2 + 3"})
        elapsed = time.monotonic() - started

        assert result == {"ok": False, "error": "Sandbox process failed; capability result rejected"}
        assert elapsed < 15, elapsed

        # The registry discards stderr, so run its exact launch command to see why it failed.
        command = registry._base_command("d8-missing-image-" + uuid.uuid4().hex[:12])
        process = subprocess.run(command, input=b"", capture_output=True, timeout=30, check=False)
        stderr = process.stderr.decode("utf-8", errors="replace")

        assert process.returncode != 0
        assert "No such image" in stderr, stderr
        assert "Unable to find image" not in stderr, stderr
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
