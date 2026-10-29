"""Fail-closed Docker-backed capability registry for the agent loop."""
from __future__ import annotations

import json
import math
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .capabilities import CapabilityRegistry


PINNED_IMAGE = (
    "python@sha256:"
    "0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce"
)
MAX_REQUEST_BYTES = 65536
MAX_RESPONSE_BYTES = 524288
DEFAULT_TIMEOUT_SECONDS = 8.0
MAX_TIMEOUT_SECONDS = 120.0
MAX_ARGUMENT_DEPTH = 32
MAX_ARGUMENT_NODES = 10000


def _bounded_json_size(
    value: Any,
    *,
    max_bytes: int = MAX_REQUEST_BYTES,
    max_depth: int = MAX_ARGUMENT_DEPTH,
    max_nodes: int = MAX_ARGUMENT_NODES,
) -> int:
    """Conservatively bound JSON size before serializing a request."""
    total = 0
    node_count = 0
    active_containers: set[int] = set()

    def add(amount: int) -> None:
        nonlocal total
        total += amount
        if total > max_bytes:
            raise ValueError("JSON request exceeds byte limit")

    def string_size(item: str) -> int:
        # A single oversized string is rejected before encoding or serialization.
        if len(item) > max_bytes:
            raise ValueError("JSON string exceeds byte limit")

        size = 2  # surrounding quotation marks
        for char in item:
            code = ord(char)
            if char in ('"', "\\"):
                size += 2
            elif code < 0x20:
                # Six bytes is a safe upper bound for JSON control escapes.
                size += 6
            elif 0xD800 <= code <= 0xDFFF:
                raise ValueError("JSON string contains an invalid Unicode surrogate")
            else:
                size += len(char.encode("utf-8"))

            if size > max_bytes:
                raise ValueError("JSON string exceeds byte limit")
        return size

    def visit(item: Any, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > max_nodes:
            raise ValueError("JSON request exceeds item-count limit")
        if depth > max_depth:
            raise ValueError("JSON request exceeds nesting-depth limit")

        if item is None:
            add(4)
        elif type(item) is bool:
            add(4 if item else 5)
        elif type(item) is str:
            add(string_size(item))
        elif type(item) is int:
            # Also prevent attempting to stringify an absurdly large integer.
            if item.bit_length() > max_bytes * 4:
                raise ValueError("JSON integer exceeds size limit")
            add(len(str(item)))
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("JSON numbers must be finite")
            add(len(json.dumps(item, allow_nan=False)))
        elif type(item) is list or type(item) is dict:
            identity = id(item)
            if identity in active_containers:
                raise ValueError("Cyclic JSON input is not supported")

            active_containers.add(identity)
            try:
                add(2)  # opening and closing brackets/braces
                if type(item) is list:
                    for index, child in enumerate(item):
                        if index:
                            add(1)  # comma
                        visit(child, depth + 1)
                else:
                    for index, (key, child) in enumerate(item.items()):
                        if type(key) is not str:
                            raise ValueError("JSON object keys must be strings")
                        if index:
                            add(1)  # comma
                        add(string_size(key))
                        add(1)  # colon
                        visit(child, depth + 1)
            finally:
                active_containers.remove(identity)
        else:
            raise ValueError("Request contains a value that is not JSON-compatible")

    visit(value, 0)
    return total

def _run_bounded_process(
    command: list[str],
    request: bytes,
    *,
    timeout_seconds: float,
    max_output_bytes: int,
) -> tuple[int, bytes, bool]:
    """Run a child process while strictly bounding captured stdout.

    Returns (returncode, stdout, output_exceeded).
    stderr is drained but never retained.
    """
    deadline = time.monotonic() + timeout_seconds
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    captured = bytearray()
    output_exceeded = threading.Event()
    reader_errors: list[BaseException] = []

    def read_stdout() -> None:
        try:
            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break

                remaining = max_output_bytes + 1 - len(captured)
                if remaining > 0:
                    captured.extend(chunk[:remaining])

                if len(captured) > max_output_bytes:
                    output_exceeded.set()
                    try:
                        process.kill()
                    except OSError:
                        pass
                    break
        except BaseException as exc:
            reader_errors.append(exc)

    def drain_stderr() -> None:
        try:
            assert process.stderr is not None
            while process.stderr.read(8192):
                pass
        except BaseException as exc:
            reader_errors.append(exc)

    write_errors: list[BaseException] = []

    def write_stdin() -> None:
        try:
            assert process.stdin is not None
            try:
                remaining = memoryview(request)
                while remaining:
                    written = process.stdin.write(remaining)
                    if written is None or written <= 0:
                        raise subprocess.SubprocessError(
                            "Input writer made no progress"
                        )
                    remaining = remaining[written:]
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                # The child may have exited or rejected the request.
                pass
            finally:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
        except BaseException as exc:
            write_errors.append(exc)

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stdin_thread = threading.Thread(target=write_stdin, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    stdin_thread.start()

    try:
        # Enforce one deadline across stdin delivery and child execution.
        remaining_seconds = max(0.0, deadline - time.monotonic())
        try:
            returncode = process.wait(timeout=remaining_seconds)
        except subprocess.TimeoutExpired:
            if process.poll() is None:
                process.kill()
            process.wait()
            raise

        # A child may exit without reading all of stdin. Do not let a writer
        # thread extend the invocation beyond the same deadline.
        remaining_seconds = max(0.0, deadline - time.monotonic())
        stdin_thread.join(timeout=remaining_seconds)
        if stdin_thread.is_alive():
            if process.poll() is None:
                process.kill()
                process.wait()
            stdin_thread.join(timeout=2)
            raise subprocess.TimeoutExpired(command, timeout_seconds)
    except BaseException:
        if process.poll() is None:
            process.kill()
            process.wait()
        if stdin_thread.is_alive():
            stdin_thread.join(timeout=2)
        raise
    finally:
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass

    if stdin_thread.is_alive():
        raise subprocess.SubprocessError("Input writer did not terminate")
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        raise subprocess.SubprocessError("Output reader did not terminate")
    if write_errors:
        raise subprocess.SubprocessError("Input stream could not be written")
    if reader_errors:
        raise subprocess.SubprocessError("Output stream could not be read")

    return returncode, bytes(captured), output_exceeded.is_set()


class CapabilitySandboxError(RuntimeError):
    """The OS sandbox could not safely execute a capability."""


class ContainerCapabilityRegistry:
    """Same registry interface, but every invocation runs in a fresh container."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        docker_executable: str = "docker.exe",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        image: str = PINNED_IMAGE,
    ):
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("Workspace must be an existing directory")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError("timeout_seconds must be a positive number")
        if timeout_seconds <= 0 or timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError(
                f"timeout_seconds must be finite and between 0 and "
                f"{MAX_TIMEOUT_SECONDS:g} seconds"
            )
        if isinstance(timeout_seconds, float) and not math.isfinite(timeout_seconds):
            raise ValueError(
                f"timeout_seconds must be finite and between 0 and "
                f"{MAX_TIMEOUT_SECONDS:g} seconds"
            )
        if image != PINNED_IMAGE:
            raise ValueError("Only the pinned sandbox image digest is accepted")
        if not isinstance(docker_executable, str) or not docker_executable.strip():
            raise ValueError("docker_executable must be a non-empty string")

        self.timeout_seconds = float(timeout_seconds)
        self.docker_executable = docker_executable
        self.image = image

        package_dir = Path(__file__).resolve().parent
        self.worker_path = package_dir / "container_worker.py"
        if not self.worker_path.is_file():
            raise CapabilitySandboxError("Container worker file is missing")

        # This object is used only to expose the established capability descriptions.
        # invoke() below never executes this in-process registry.
        self._description_registry = CapabilityRegistry(self.workspace)

    @property
    def descriptions(self) -> list[dict[str, str]]:
        return self._description_registry.descriptions

    def _base_command(self, container_name: str) -> list[str]:
        workspace_source = self.workspace.as_posix()
        package_source = self.worker_path.parent.as_posix()
        worker_source = self.worker_path.as_posix()

        # --mount uses comma-delimited options. Refuse ambiguous source paths.
        if any("," in item for item in (workspace_source, package_source, worker_source)):
            raise CapabilitySandboxError("Sandbox source paths cannot contain commas")

        return [
            self.docker_executable, "run", "-i",
            "--name", container_name,
            "--rm",
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges=true",
            "--pids-limit", "32",
            "--memory", "128m",
            "--cpus", "0.5",
            "--user", "65534:65534",
            "--mount", f"type=bind,source={workspace_source},target=/workspace,readonly",
            "--mount", f"type=bind,source={package_source},target=/opt/package/self_improving_agents,readonly",
            "--mount", f"type=bind,source={worker_source},target=/opt/container_worker.py,readonly",
            self.image,
            "python", "-I", "/opt/container_worker.py",
        ]

    def _remove_container(self, container_name: str) -> bool:
        """Remove the container or confirm it is absent."""
        try:
            removed = subprocess.run(
                [self.docker_executable, "rm", "-f", container_name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
            )
            if removed.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            pass

        # A failed rm may mean --rm already removed the container.
        # A Docker error is not itself proof that the container is absent.
        try:
            probe = subprocess.run(
                [self.docker_executable, 'ps', '-aq', '--filter',
                 f"name={container_name}"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
                text=True,
            )
            return probe.returncode == 0 and not probe.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return False

    def invoke(self, name: str, arguments: Any) -> dict[str, Any]:
        if not isinstance(name, str) or name not in {
            "calculator", "read_text_file", "search_text"
        }:
            return {"ok": False, "error": f"Capability is not allowlisted: {name!r}"}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "Tool arguments must be a JSON object"}

        payload = {"name": name, "arguments": arguments}
        try:
            _bounded_json_size(payload)
            request = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (
            TypeError,
            ValueError,
            UnicodeError,
            OverflowError,
            RecursionError,
        ) as exc:
            if "byte limit" in str(exc):
                message = "Capability request exceeds input byte limit"
            else:
                message = "Capability request is invalid or exceeds safety limits"
            return {"ok": False, "error": message}

        # Retain the exact post-serialization check as a final defense.
        if len(request) > MAX_REQUEST_BYTES:
            return {"ok": False, "error": "Capability request exceeds input byte limit"}

        container_name = f"skill-agents-cap-{uuid.uuid4().hex[:20]}"
        command = self._base_command(container_name)


        try:
            returncode, stdout, output_exceeded = _run_bounded_process(
                command,
                request,
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=MAX_RESPONSE_BYTES,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": "Sandbox execution timed out; capability not accepted",
            }
        except OSError:
            return {
                "ok": False,
                "error": "Sandbox launch failed; capability not executed",
            }
        except subprocess.SubprocessError:
            return {
                "ok": False,
                "error": "Sandbox output handling failed; capability not accepted",
            }
        finally:
            cleanup_confirmed = self._remove_container(container_name)
            if not cleanup_confirmed:
                raise CapabilitySandboxError(
                    "Sandbox container cleanup could not be confirmed; capability result rejected"
                )

        if output_exceeded:
            return {
                "ok": False,
                "error": "Sandbox response exceeds output byte limit",
            }

        if returncode != 0:
            return {
                "ok": False,
                "error": "Sandbox process failed; capability result rejected",
            }

        try:
            result = json.loads(stdout.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"ok": False, "error": "Sandbox returned an invalid response"}

        if not isinstance(result, dict) or type(result.get("ok")) is not bool:
            return {"ok": False, "error": "Sandbox response schema is invalid"}
        if result["ok"] and "result" not in result:
            return {"ok": False, "error": "Sandbox success response is missing its result"}
        if not result["ok"] and not isinstance(result.get("error"), str):
            return {"ok": False, "error": "Sandbox failure response is invalid"}
        return result