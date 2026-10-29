import subprocess

import pytest

import self_improving_agents.container_capabilities as container_module
from self_improving_agents.container_capabilities import (
    CapabilitySandboxError,
    ContainerCapabilityRegistry,
)


def completed(returncode, stdout=""):
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


def test_cleanup_confirms_successful_rm(tmp_path, monkeypatch):
    registry = ContainerCapabilityRegistry(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return completed(0)

    monkeypatch.setattr(container_module.subprocess, "run", fake_run)

    assert registry._remove_container("skill-agents-cap-test") is True
    assert len(calls) == 1
    assert calls[0][1:3] == ["rm", "-f"]


def test_cleanup_confirms_absence_when_rm_reports_already_removed(
    tmp_path, monkeypatch
):
    registry = ContainerCapabilityRegistry(tmp_path)
    replies = iter([completed(1), completed(0, "")])

    monkeypatch.setattr(
        container_module.subprocess,
        "run",
        lambda *args, **kwargs: next(replies),
    )

    assert registry._remove_container("skill-agents-cap-test") is True


def test_cleanup_fails_when_container_is_still_present(tmp_path, monkeypatch):
    registry = ContainerCapabilityRegistry(tmp_path)
    replies = iter([completed(1), completed(0, "container-id\n")])

    monkeypatch.setattr(
        container_module.subprocess,
        "run",
        lambda *args, **kwargs: next(replies),
    )

    assert registry._remove_container("skill-agents-cap-test") is False


def test_cleanup_is_unconfirmed_when_docker_is_unavailable(
    tmp_path, monkeypatch
):
    registry = ContainerCapabilityRegistry(tmp_path)

    def unavailable(*args, **kwargs):
        raise FileNotFoundError("simulated Docker CLI failure")

    monkeypatch.setattr(container_module.subprocess, "run", unavailable)

    assert registry._remove_container("skill-agents-cap-test") is False


def test_invoke_rejects_result_when_cleanup_is_unconfirmed(
    tmp_path, monkeypatch
):
    registry = ContainerCapabilityRegistry(tmp_path)
    cleanup_names = []

    monkeypatch.setattr(
        container_module,
        "_run_bounded_process",
        lambda *args, **kwargs: (0, b'{"ok":true,"result":4}', False),
    )
    monkeypatch.setattr(
        registry,
        "_remove_container",
        lambda name: cleanup_names.append(name) or False,
    )

    with pytest.raises(
        CapabilitySandboxError,
        match="cleanup could not be confirmed",
    ):
        registry.invoke("calculator", {"expression": "2+2"})

    assert len(cleanup_names) == 1


def test_invoke_preserves_result_when_cleanup_is_confirmed(
    tmp_path, monkeypatch
):
    registry = ContainerCapabilityRegistry(tmp_path)
    cleanup_names = []

    monkeypatch.setattr(
        container_module,
        "_run_bounded_process",
        lambda *args, **kwargs: (0, b'{"ok":true,"result":4}', False),
    )
    monkeypatch.setattr(
        registry,
        "_remove_container",
        lambda name: cleanup_names.append(name) or True,
    )

    result = registry.invoke("calculator", {"expression": "2+2"})

    assert result == {"ok": True, "result": 4}
    assert len(cleanup_names) == 1
