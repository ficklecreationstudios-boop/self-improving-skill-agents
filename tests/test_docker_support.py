"""A Docker check that does not answer must fail a run that promised a sandbox, and must say why."""
import subprocess

import pytest

import test_container_capabilities as capabilities
import test_container_missing_image as missing_image
import test_container_os_sandbox as os_sandbox
import test_container_workspace_integration as workspace
from docker_support import DOCKER_CHECK_TIMEOUT
from test_forced_attack_enforcement import real_container_root  # noqa: F401 (fixture)

SkipException = pytest.skip.Exception
FailException = pytest.fail.Exception


@pytest.fixture
def hung_docker(monkeypatch):
    """Every Docker check times out; records the limit each one asked for."""
    limits = []

    def run(command, **kwargs):
        limits.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", run)
    return limits


CHECKS = [
    ("capabilities", lambda request: capabilities.test_real_docker_container_integration()),
    ("missing_image", lambda request: missing_image.test_missing_image_fails_closed_without_pull(request.getfixturevalue("monkeypatch"))),
    ("os_sandbox", lambda request: os_sandbox.test_real_container_enforces_os_sandbox_controls()),
    ("workspace", lambda request: workspace.test_real_container_reads_searches_and_rejects_mount_escape()),
    ("forced_attack", lambda request: request.getfixturevalue("real_container_root")),
]
IDS = [name for name, _ in CHECKS]
FUNCTIONS = [check for _, check in CHECKS]


@pytest.mark.parametrize("check", FUNCTIONS, ids=IDS)
def test_unresponsive_docker_fails_when_a_sandbox_was_promised(check, request, hung_docker, monkeypatch):
    monkeypatch.setenv("D8_REQUIRE_DOCKER", "1")
    # Catch both: a skip escaping pytest.raises would mark this test skipped, hiding the very thing it checks.
    with pytest.raises((FailException, SkipException), match="timed out") as raised:
        check(request)
    assert raised.type is FailException, "a promised sandbox run skipped instead of failing"
    assert "D8_REQUIRE_DOCKER=1" in str(raised.value)
    assert hung_docker == [DOCKER_CHECK_TIMEOUT]


@pytest.mark.parametrize("check", FUNCTIONS, ids=IDS)
def test_unresponsive_docker_skips_with_the_reason_otherwise(check, request, hung_docker, monkeypatch):
    monkeypatch.delenv("D8_REQUIRE_DOCKER", raising=False)
    with pytest.raises(SkipException, match="timed out"):
        check(request)


def test_the_limit_is_for_checks_and_leaves_the_sandbox_limit_alone():
    from self_improving_agents import container_capabilities
    assert DOCKER_CHECK_TIMEOUT == 30
    assert container_capabilities.DEFAULT_TIMEOUT_SECONDS == 8.0
