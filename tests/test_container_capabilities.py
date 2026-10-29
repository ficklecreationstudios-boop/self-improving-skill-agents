import io
import json
import shutil
import subprocess
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from self_improving_agents import container_capabilities as sandbox
from self_improving_agents.capabilities import CapabilityRegistry


def make_registry(tmp_path, **kwargs):
    return sandbox.ContainerCapabilityRegistry(tmp_path, **kwargs)


def completed(stdout=b'{"ok":true,"result":{"value":5,"expression":"2 + 3"}}',
              returncode=0):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=b"")


def mock_docker_run(monkeypatch, result=None, exception=None):
    """Mock both the Docker capability process and the cleanup command."""
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        if len(command) > 1 and command[1] == "rm":
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        if exception is not None:
            raise exception

        outcome = result or completed()

        class FakeProcess:
            def __init__(self):
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO(outcome.stdout)
                self.stderr = io.BytesIO(outcome.stderr)
                self.returncode = outcome.returncode

            def wait(self, timeout=None):
                return self.returncode

            def poll(self):
                return self.returncode

            def kill(self):
                self.returncode = -9

        return FakeProcess()

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    monkeypatch.setattr(sandbox.subprocess, "Popen", fake_popen)
    return calls

def test_calculator_result_is_returned_from_container(tmp_path, monkeypatch):
    registry = make_registry(tmp_path)
    calls = mock_docker_run(monkeypatch)

    result = registry.invoke("calculator", {"expression": "2 + 3"})

    assert result == {
        "ok": True,
        "result": {"value": 5, "expression": "2 + 3"},
    }
    launch = next(c[0] for c in calls if len(c[0]) > 1 and c[0][1] == "run")
    assert launch[0] == "docker.exe"
    assert registry.image == sandbox.PINNED_IMAGE


def test_unknown_capability_fails_without_launch(tmp_path, monkeypatch):
    registry = make_registry(tmp_path)
    calls = mock_docker_run(monkeypatch)

    result = registry.invoke("shell", {"command": "whoami"})

    assert result["ok"] is False
    assert "not allowlisted" in result["error"]
    assert not any(len(c[0]) > 1 and c[0][1] == "run" for c in calls)


def test_non_object_arguments_fail_without_launch(tmp_path, monkeypatch):
    registry = make_registry(tmp_path)
    calls = mock_docker_run(monkeypatch)

    result = registry.invoke("calculator", ["2 + 3"])

    assert result["ok"] is False
    assert "JSON object" in result["error"]
    assert not any(len(c[0]) > 1 and c[0][1] == "run" for c in calls)


def test_request_byte_limit_is_enforced(tmp_path, monkeypatch):
    registry = make_registry(tmp_path)
    calls = mock_docker_run(monkeypatch)

    result = registry.invoke(
        "read_text_file",
        {"path": "x" * sandbox.MAX_REQUEST_BYTES},
    )

    assert result["ok"] is False
    assert "byte limit" in result["error"]
    assert not any(len(c[0]) > 1 and c[0][1] == "run" for c in calls)


def test_container_nonzero_exit_rejects_result(tmp_path, monkeypatch):
    registry = make_registry(tmp_path)
    mock_docker_run(monkeypatch, result=completed(b'{"ok":true}', 1))

    result = registry.invoke("calculator", {"expression": "2 + 3"})

    assert result["ok"] is False
    assert "process failed" in result["error"]


def test_malformed_json_rejects_result(tmp_path, monkeypatch):
    registry = make_registry(tmp_path)
    mock_docker_run(monkeypatch, result=completed(b"not-json"))

    result = registry.invoke("calculator", {"expression": "2 + 3"})

    assert result["ok"] is False
    assert "invalid response" in result["error"]


def test_oversized_response_is_rejected(tmp_path, monkeypatch):
    registry = make_registry(tmp_path)
    payload = b" " * (sandbox.MAX_RESPONSE_BYTES + 1)
    mock_docker_run(monkeypatch, result=completed(payload))

    result = registry.invoke("calculator", {"expression": "2 + 3"})

    assert result["ok"] is False
    assert "output byte limit" in result["error"]


def test_timeout_fails_closed_and_requests_cleanup(tmp_path, monkeypatch):
    registry = make_registry(tmp_path, timeout_seconds=0.25)
    calls = mock_docker_run(
        monkeypatch,
        exception=subprocess.TimeoutExpired("docker.exe", 0.25),
    )

    result = registry.invoke("calculator", {"expression": "2 + 3"})

    assert result["ok"] is False
    assert "timed out" in result["error"]
    assert any(len(c[0]) > 1 and c[0][1] == "rm" for c in calls)


def test_docker_launch_error_fails_closed(tmp_path, monkeypatch):
    registry = make_registry(tmp_path)
    calls = mock_docker_run(monkeypatch, exception=OSError("docker unavailable"))

    result = registry.invoke("calculator", {"expression": "2 + 3"})

    assert result["ok"] is False
    assert "launch failed" in result["error"]
    assert any(len(c[0]) > 1 and c[0][1] == "rm" for c in calls)


def test_docker_failure_never_falls_back_to_host_registry(tmp_path, monkeypatch):
    registry = make_registry(tmp_path)
    calls = mock_docker_run(monkeypatch, exception=OSError("docker unavailable"))

    def forbidden_host_execution(*args, **kwargs):
        raise AssertionError("in-process capability execution is forbidden")

    monkeypatch.setattr(CapabilityRegistry, "invoke", forbidden_host_execution)

    result = registry.invoke("calculator", {"expression": "2 + 3"})

    assert result["ok"] is False
    assert "launch failed" in result["error"]
    assert any(len(c[0]) > 1 and c[0][1] == "run" for c in calls)


def test_security_flags_are_present(tmp_path):
    registry = make_registry(tmp_path)
    command = registry._base_command("test-container")

    assert registry.image == sandbox.PINNED_IMAGE
    assert "--pull" in command and command[command.index("--pull") + 1] == "never"
    assert command.index("--pull") < command.index(registry.image)
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert "--cap-drop" in command and command[command.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in command
    assert "no-new-privileges=true" in command
    assert "--pids-limit" in command and command[command.index("--pids-limit") + 1] == "32"
    assert "--memory" in command and command[command.index("--memory") + 1] == "128m"
    assert "--cpus" in command and command[command.index("--cpus") + 1] == "0.5"
    assert "--user" in command and command[command.index("--user") + 1] == "65534:65534"

    mounts = [command[i + 1] for i, item in enumerate(command[:-1]) if item == "--mount"]
    assert len(mounts) == 3
    assert all("readonly" in mount for mount in mounts)


def test_only_pinned_image_is_accepted(tmp_path):
    with pytest.raises(ValueError, match="pinned sandbox image"):
        make_registry(tmp_path, image="python:latest")


def test_invalid_response_schema_is_rejected(tmp_path, monkeypatch):
    registry = make_registry(tmp_path)
    mock_docker_run(monkeypatch, result=completed(b'{"ok":"yes","result":5}'))

    result = registry.invoke("calculator", {"expression": "2 + 3"})

    assert result["ok"] is False
    assert "schema" in result["error"]


def test_real_docker_container_integration():
    # Docker Desktop denies this host's C:\\Users\\...\\Temp bind mounts.
    # Keep the real integration workspace beneath the D: checkout.
    # This test skips only when Docker or the pinned image is unavailable.
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
            ["docker.exe", "image", "inspect", sandbox.PINNED_IMAGE],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if image.returncode != 0:
            pytest.skip("Pinned sandbox image is not locally available")
    except (OSError, subprocess.SubprocessError):
        pytest.skip("Docker CLI or daemon is unavailable")

    repo_root = Path(__file__).resolve().parents[1]
    workspace = repo_root / f".d8-docker-integration-{uuid.uuid4().hex}"
    workspace.mkdir()
    try:
        registry = make_registry(workspace)
        result = registry.invoke("calculator", {"expression": "2 + 3"})

        assert result["ok"] is True, result
        assert result["result"]["value"] == 5
    finally:
        shutil.rmtree(workspace, ignore_errors=True)



def test_bounded_runner_caps_captured_stdout(monkeypatch):
    limit = 1024
    process_state = {"killed": False}

    class FakeProcess:
        def __init__(self):
            self.stdin = io.BytesIO()
            self.stdout = io.BytesIO(b"x" * (limit * 100))
            self.stderr = io.BytesIO(b"")
            self.returncode = 0

        def wait(self, timeout=None):
            return self.returncode

        def poll(self):
            return self.returncode

        def kill(self):
            process_state["killed"] = True
            self.returncode = -9

    monkeypatch.setattr(
        sandbox.subprocess,
        "Popen",
        lambda *args, **kwargs: FakeProcess(),
    )

    returncode, captured, exceeded = sandbox._run_bounded_process(
        ["fake-docker"],
        b"{}",
        timeout_seconds=1,
        max_output_bytes=limit,
    )

    assert exceeded is True
    assert len(captured) == limit + 1
    assert process_state["killed"] is True
