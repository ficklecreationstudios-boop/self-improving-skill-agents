import subprocess
import sys
import time

import pytest

from self_improving_agents.container_capabilities import _run_bounded_process


def test_deadline_covers_blocked_stdin_write():
    # This child deliberately does not consume stdin. A multi-megabyte request
    # fills the pipe and forces the parent writer to block on Windows.
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    request = b"x" * (8 * 1024 * 1024)
    started = time.monotonic()

    with pytest.raises(subprocess.TimeoutExpired):
        _run_bounded_process(
            command,
            request,
            timeout_seconds=0.5,
            max_output_bytes=1024,
        )

    elapsed = time.monotonic() - started
    assert elapsed < 5.0, f"blocked stdin exceeded its deadline: {elapsed:.2f}s"


def test_normal_stdin_write_and_response_still_work():
    command = [
        sys.executable,
        "-c",
        "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)",
    ]

    result = _run_bounded_process(
        command,
        b"d8-stdin-regression",
        timeout_seconds=5.0,
        max_output_bytes=1024,
    )

    assert result == (0, b"d8-stdin-regression", False)
