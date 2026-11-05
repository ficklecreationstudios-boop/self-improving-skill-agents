"""Shared gate for tests that need a real Docker daemon and the pinned sandbox image."""
import os
from pathlib import Path

import pytest

from self_improving_agents.container_capabilities import DEFAULT_DOCKER as DOCKER  # noqa: F401

# How long a Docker check may take. A busy CI runner has been slower than 5 s; this is not a sandbox limit.
DOCKER_CHECK_TIMEOUT = 30


def docker_unavailable(reason: str):
    """Skip, unless this run promised a sandbox (D8_REQUIRE_DOCKER=1): then a skip would hide missing coverage."""
    if os.environ.get("D8_REQUIRE_DOCKER") == "1":
        pytest.fail(f"D8_REQUIRE_DOCKER=1 but the real sandbox cannot run: {reason}")
    pytest.skip(reason)


def container_test_root() -> Path:
    """The folder real sandbox tests work in. It must be one Docker can bind-mount; failing here is deliberate."""
    value = os.environ.get("D8_CONTAINER_TEST_ROOT")
    if not value:
        pytest.fail("D8_CONTAINER_TEST_ROOT must name an existing folder Docker can bind-mount")
    root = Path(value).resolve()
    if not root.is_dir():
        pytest.fail(f"D8_CONTAINER_TEST_ROOT is not an existing folder: {root}")
    return root
