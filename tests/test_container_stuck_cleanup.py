"""A container that never answers must be stopped at the deadline and actually removed."""
import subprocess
import time

from self_improving_agents import container_capabilities as sandbox
from test_forced_attack_enforcement import _layout, real_container_root  # noqa: F401 (fixture)

TIMEOUT_SECONDS = 3


def _containers_named(name):
    probe = subprocess.run(["docker.exe", "ps", "-aq", "--filter", f"name=^/{name}$"],
                           capture_output=True, text=True, timeout=10, check=False)
    assert probe.returncode == 0, probe.stderr
    return probe.stdout.split()


def test_real_stuck_container_times_out_and_is_removed(real_container_root, monkeypatch):
    workspace, _, _ = _layout(real_container_root)
    registry = sandbox.ContainerCapabilityRegistry(workspace, timeout_seconds=TIMEOUT_SECONDS)
    launched = []
    original = registry._base_command

    def stuck_command(container_name):
        # Same security flags and mounts; only the worker is replaced by one that never answers.
        command = original(container_name)
        launched.append(container_name)
        return command[:command.index(sandbox.PINNED_IMAGE) + 1] + [
            "python", "-I", "-c", "import time; time.sleep(120)"]

    monkeypatch.setattr(registry, "_base_command", stuck_command)
    try:
        started = time.monotonic()
        result = registry.invoke("calculator", {"expression": "1 + 1"})
        elapsed = time.monotonic() - started

        assert result == {"ok": False, "error": "Sandbox execution timed out; capability not accepted"}
        assert TIMEOUT_SECONDS <= elapsed < TIMEOUT_SECONDS + 15, elapsed
        assert len(launched) == 1
        assert _containers_named(launched[0]) == []
    finally:
        for name in launched:
            subprocess.run(["docker.exe", "rm", "-f", name], capture_output=True, timeout=30, check=False)
