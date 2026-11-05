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
from docker_support import container_test_root, DOCKER, DOCKER_CHECK_TIMEOUT, docker_unavailable

MISSING_IMAGE = "python@sha256:" + "0" * 64


def test_missing_image_fails_closed_without_pull(monkeypatch):
    try:
        info = subprocess.run([DOCKER, "info", "--format", "{{.ServerVersion}}"],
                              capture_output=True, timeout=DOCKER_CHECK_TIMEOUT, check=False)
        if info.returncode != 0:
            docker_unavailable("Docker daemon is unavailable")
        # Same host gate as the other real-Docker tests: run only where the sandbox is set up.
        pinned = subprocess.run([DOCKER, "image", "inspect", sandbox.PINNED_IMAGE],
                                capture_output=True, timeout=DOCKER_CHECK_TIMEOUT, check=False)
        if pinned.returncode != 0:
            docker_unavailable("Pinned sandbox image is unavailable")
        present = subprocess.run([DOCKER, "image", "inspect", MISSING_IMAGE],
                                 capture_output=True, timeout=DOCKER_CHECK_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        docker_unavailable(f"Docker CLI or daemon is unavailable: {exc}")
    if present.returncode == 0:
        pytest.fail("The all-zero test digest unexpectedly exists locally")

    root = container_test_root()

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
