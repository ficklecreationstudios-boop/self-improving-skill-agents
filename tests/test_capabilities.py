import json
from self_improving_agents.capabilities import CapabilityRegistry
from self_improving_agents.agent_loop import run_agent_loop
from self_improving_agents.models import Task


def test_calculator_allows_arithmetic_but_not_code(tmp_path):
    registry = CapabilityRegistry(tmp_path)
    assert registry.invoke("calculator", {"expression": "(2 + 3) * 4"})["result"]["value"] == 20
    rejected = registry.invoke("calculator", {"expression": "__import__('os').system('echo bad')"})
    assert not rejected["ok"]
    assert registry.invoke("calculator", {"expression": "2 ** 100"})["ok"] is False


def test_read_file_and_search_are_confined_to_workspace(tmp_path):
    root = tmp_path / "workspace"; root.mkdir()
    (root / "notes.md").write_text("The answer is 42.", encoding="utf-8")
    outside = tmp_path / "secret.txt"; outside.write_text("do not read", encoding="utf-8")
    registry = CapabilityRegistry(root)
    assert registry.invoke("read_text_file", {"path": "notes.md"})["result"]["content"] == "The answer is 42."
    escaped = registry.invoke("read_text_file", {"path": "../secret.txt"})
    assert not escaped["ok"]
    assert registry.invoke("search_text", {"query": "42"})["result"]["matches"][0]["path"] == "notes.md"


def test_unknown_capabilities_fail_closed(tmp_path):
    registry = CapabilityRegistry(tmp_path)
    result = registry.invoke("run_shell", {"command": "whoami"})
    assert result["ok"] is False
    assert result["error"].startswith("Capability is not allowlisted")


def test_tool_loop_invokes_only_registered_tool_and_then_finishes(tmp_path):
    registry = CapabilityRegistry(tmp_path)
    class FakeAdapter:
        configured = True
        def __init__(self): self.calls = 0
        def generate(self, prompt):
            self.calls += 1
            if self.calls == 1:
                return json.dumps({"type":"tool_call","name":"calculator","arguments":{"expression":"6*7"}})
            assert "tool_result_untrusted" in prompt
            return json.dumps({"type":"final","answer":"The result is 42."})
    result = run_agent_loop(Task("Calculate 6 times 7"), FakeAdapter(), registry)
    assert result.output == "The result is 42."
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["result"]["result"]["value"] == 42


def test_tool_loop_never_executes_unknown_tool(tmp_path):
    registry = CapabilityRegistry(tmp_path)
    class FakeAdapter:
        configured = True
        def generate(self, _prompt):
            return json.dumps({"type":"tool_call","name":"run_shell","arguments":{"command":"bad"}})
    result = run_agent_loop(Task("run something"), FakeAdapter(), registry, max_steps=1)
    assert result.tool_calls[0]["result"]["ok"] is False
    assert result.tool_calls[0]["result"]["error"].startswith("Capability is not allowlisted")
