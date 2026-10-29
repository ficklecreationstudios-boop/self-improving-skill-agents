import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from self_improving_agents import cli


def _summary(output):
    decoder = json.JSONDecoder()
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "stop_reason" in value:
            return value
    raise AssertionError("No valid agent summary JSON found in CLI output")


def _configure_cli(monkeypatch, tmp_path, result):
    monkeypatch.setattr(cli, "discover_skills", lambda _root: [])
    monkeypatch.setattr(cli, "select_skills", lambda _task, _domain, _skills: [])
    monkeypatch.setattr(cli, "ContainerCapabilityRegistry", lambda _workspace: object())
    monkeypatch.setattr(cli, "OllamaAdapter", lambda: object())
    monkeypatch.setattr(cli, "run_agent_task", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        "sys.argv",
        [
            "skill-agents",
            "agent",
            "Perform a test",
            "--workspace",
            str(tmp_path),
            "--audit",
            str(tmp_path / "audit.jsonl"),
        ],
    )


@pytest.mark.parametrize(
    "stop_reason",
    [
        "invalid_response_treated_as_final",
        "non_json_treated_as_final",
        "step_limit",
    ],
)
def test_agent_cli_exits_nonzero_for_stopped_task(
    monkeypatch, capsys, tmp_path, stop_reason
):
    result = SimpleNamespace(
        output="Agent stopped before producing a valid final answer.",
        tool_calls=(),
        task_digest="a" * 64,
        output_digest="b" * 64,
        steps=0,
        stop_reason=stop_reason,
    )
    _configure_cli(monkeypatch, tmp_path, result)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code != 0
    assert stop_reason in str(exc.value.code)

    captured = capsys.readouterr()
    assert "Agent stopped before producing a valid final answer." in captured.out
    assert _summary(captured.out)["stop_reason"] == stop_reason


def test_agent_cli_keeps_successful_final_answer_exit_zero(
    monkeypatch, capsys, tmp_path
):
    result = SimpleNamespace(
        output="The answer is 391.",
        tool_calls=(),
        task_digest="a" * 64,
        output_digest="b" * 64,
        steps=0,
        stop_reason="final_answer",
    )
    _configure_cli(monkeypatch, tmp_path, result)

    # A normal return from main() means it did not raise SystemExit.
    cli.main()

    captured = capsys.readouterr()
    assert "The answer is 391." in captured.out
    assert _summary(captured.out)["stop_reason"] == "final_answer"

def test_agent_cli_requires_explicit_workspace(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        ["skill-agents", "agent", "Perform a test"],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2


def test_agent_cli_missing_workspace_has_argparse_exit_status():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "self_improving_agents.cli",
            "agent",
            "Perform a test",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2, (
        f"expected argparse exit status 2, got {result.returncode}; "
        f"stdout={result.stdout!r}; stderr={result.stderr!r}"
    )
    assert "--workspace" in result.stderr
    assert "required" in result.stderr