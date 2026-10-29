import json
import os
import shutil
import socket
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from self_improving_agents.container_capabilities import (
    ContainerCapabilityRegistry,
    PINNED_IMAGE,
)


_PROBE = r'''
import json
import os
import socket
import subprocess
import sys

def blocked(operation):
    try:
        operation()
        return False, "unexpected success"
    except OSError as exc:
        return True, "{}: {}".format(type(exc).__name__, exc)
    except Exception as exc:
        return False, "unexpected exception: {}: {}".format(type(exc).__name__, exc)

def unexpected_exception():
    raise RuntimeError("probe sentinel: this is not an OS-level denial")

def root_write():
    with open("/d8-os-sandbox-root-write-probe", "w") as f:
        f.write("probe")

def workspace_write():
    with open("/workspace/d8-os-sandbox-workspace-write-probe", "w") as f:
        f.write("probe")

def package_write():
    with open("/opt/package/self_improving_agents/capabilities.py", "a") as f:
        f.write("")

def outbound_connect():
    with socket.create_connection(("1.1.1.1", 443), timeout=1):
        pass

status = {}
with open("/proc/self/status", encoding="utf-8") as f:
    for line in f:
        if line.startswith(("CapEff:", "NoNewPrivs:", "Seccomp:")):
            key, value = line.split(":", 1)
            status[key] = value.strip()

def read_cgroup(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError as exc:
        return "UNAVAILABLE: {}".format(type(exc).__name__)

checks = {}
checks["unexpected_exception"] = blocked(unexpected_exception)
checks["root_filesystem_write"] = blocked(root_write)
checks["workspace_mount_write"] = blocked(workspace_write)
checks["package_mount_write"] = blocked(package_write)
checks["outbound_network"] = blocked(outbound_connect)

children = []
blocked_at = None
process_error = None
try:
    for index in range(40):
        try:
            child = subprocess.Popen(
                [
                    sys.executable, "-I", "-c",
                    "import time; time.sleep(15)",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            children.append(child)
        except OSError as exc:
            blocked_at = index
            process_error = "{}: {}".format(type(exc).__name__, exc)
            break
finally:
    for child in children:
        if child.poll() is None:
            child.kill()
    for child in children:
        try:
            child.wait(timeout=3)
        except Exception:
            pass

children_cleanup = all(child.poll() is not None for child in children)

result = {
    "uid": os.getuid(),
    "gid": os.getgid(),
    "CapEff": status.get("CapEff"),
    "NoNewPrivs": status.get("NoNewPrivs"),
    "Seccomp": status.get("Seccomp"),
    "pids_max": read_cgroup("/sys/fs/cgroup/pids.max"),
    "memory_max": read_cgroup("/sys/fs/cgroup/memory.max"),
    "cpu_max": read_cgroup("/sys/fs/cgroup/cpu.max"),
    "checks": {
        key: {"blocked": value[0], "detail": value[1]}
        for key, value in checks.items()
    },
    "process_creation_blocked_at": blocked_at,
    "process_creation_error": process_error,
    "children_started": len(children),
    "children_cleanup": children_cleanup,
}
print(json.dumps(result, sort_keys=True))
'''

def test_real_container_enforces_os_sandbox_controls():
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
        pytest.fail("D8_CONTAINER_TEST_ROOT must specify an accessible D: directory")

    root = Path(root_value).resolve()
    if not root.is_dir() or root.drive.upper() != "D:":
        pytest.fail("OS sandbox test workspace root must be on D:")

    workspace = root / ("d8-os-sandbox-" + uuid.uuid4().hex[:16])
    workspace.mkdir()

    container_name = "d8-os-check-" + uuid.uuid4().hex[:20]
    try:
        registry = ContainerCapabilityRegistry(workspace, timeout_seconds=20)
        command = registry._base_command(container_name)

        # Preserve the application's configured security flags and all
        # three read-only mounts, replacing only the worker entrypoint.
        image_index = command.index(PINNED_IMAGE)
        command = command[:image_index + 1] + [
            "python", "-I", "-c", _PROBE
        ]

        try:
            process = subprocess.run(
                command,
                input=b"",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=35,
                check=False,
            )
        except subprocess.TimeoutExpired:
            registry._remove_container(container_name)
            pytest.fail("OS sandbox probe timed out; cleanup requested")

        assert process.returncode == 0, (
            "OS probe failed: exit={!r}, stdout={!r}, stderr={!r}".format(
                process.returncode,
                process.stdout[:3000],
                process.stderr[:5000],
            )
        )

        try:
            evidence = json.loads(process.stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            pytest.fail(
                "OS probe did not return JSON: {}; stdout={!r}; stderr={!r}".format(
                    exc, process.stdout[:3000], process.stderr[:3000]
                )
            )

        assert evidence["uid"] == 65534, evidence
        assert evidence["CapEff"] is not None, evidence
        assert int(evidence["CapEff"], 16) == 0, evidence
        assert evidence["NoNewPrivs"] == "1", evidence
        assert evidence["Seccomp"] == "2", evidence

        assert evidence["pids_max"] == "32", evidence
        assert evidence["memory_max"] == "134217728", evidence
        assert evidence["cpu_max"] == "50000 100000", evidence

        assert evidence["checks"]["unexpected_exception"]["blocked"] is False, evidence
        assert "unexpected exception" in evidence["checks"]["unexpected_exception"]["detail"], evidence

        for key in (
            "root_filesystem_write",
            "workspace_mount_write",
            "package_mount_write",
            "outbound_network",
        ):
            assert evidence["checks"][key]["blocked"] is True, evidence

        assert evidence["process_creation_blocked_at"] is not None, evidence
        assert evidence["process_creation_blocked_at"] < 40, evidence
        assert evidence["children_started"] < 40, evidence
        assert evidence["children_cleanup"] is True, evidence

    finally:
        shutil.rmtree(workspace, ignore_errors=True)
