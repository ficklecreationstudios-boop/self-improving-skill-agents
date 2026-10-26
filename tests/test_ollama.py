import json
from urllib.error import HTTPError, URLError

import pytest
from self_improving_agents import ollama


class FakeResponse:
    def __init__(self, payload=None, raw=None):
        self.payload = payload
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        raw = self.raw if self.raw is not None else json.dumps(self.payload).encode("utf-8")
        return raw if size < 0 else raw[:size]


def test_unconfigured_adapter_does_not_make_network_request(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("network must not be used without an explicit model")
    monkeypatch.setattr(ollama, "urlopen", unexpected)
    adapter = ollama.OllamaAdapter(model=None)
    assert not adapter.configured
    assert "No Ollama model configured" in adapter.generate("hello")


def test_configured_adapter_sends_chat_request_to_configured_endpoint(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"message": {"content": "local response"}})

    monkeypatch.setattr(ollama, "urlopen", fake_urlopen)
    adapter = ollama.OllamaAdapter(model="qwen3:8b", base_url="http://127.0.0.1:11434", timeout=12)
    assert adapter.generate("hello") == "local response"
    assert seen["url"] == "http://127.0.0.1:11434/api/chat"
    assert seen["timeout"] == 12
    assert seen["body"]["model"] == "qwen3:8b"
    assert seen["body"]["messages"] == [{"role": "user", "content": "hello"}]
    assert seen["body"]["stream"] is False


def test_configured_adapter_rejects_malformed_response(monkeypatch):
    monkeypatch.setattr(ollama, "urlopen", lambda *_args, **_kwargs: FakeResponse({"unexpected": "shape"}))
    adapter = ollama.OllamaAdapter(model="qwen3:8b")
    with pytest.raises(RuntimeError, match="missing message.content"):
        adapter.generate("hello")


def test_configured_adapter_surfaces_unreachable_endpoint(monkeypatch):
    def fail(*_args, **_kwargs):
        raise URLError("offline")
    monkeypatch.setattr(ollama, "urlopen", fail)
    adapter = ollama.OllamaAdapter(model="qwen3:8b")
    with pytest.raises(RuntimeError, match="Ollama request failed"):
        adapter.generate("hello")


def test_prompt_and_response_sizes_are_bounded(monkeypatch):
    adapter = ollama.OllamaAdapter(model="qwen3:8b")
    with pytest.raises(RuntimeError, match="prompt exceeds"):
        adapter.generate("x" * (ollama.MAX_PROMPT_CHARS + 1))
    monkeypatch.setattr(ollama, "urlopen", lambda *_args, **_kwargs: FakeResponse(
        {"message": {"content": "x" * (ollama.MAX_OUTPUT_CHARS + 1)}}))
    with pytest.raises(RuntimeError, match="output exceeds"):
        adapter.generate("hello")


def test_absolute_paths_are_not_accepted_for_workspace_reads(tmp_path):
    from self_improving_agents.capabilities import CapabilityRegistry
    root = tmp_path / "workspace"
    root.mkdir()
    target = root / "note.txt"
    target.write_text("safe", encoding="utf-8")
    registry = CapabilityRegistry(root)
    assert registry.invoke("read_text_file", {"path": str(target.resolve())})["ok"] is False


def test_configured_adapter_rejects_invalid_json(monkeypatch):
    monkeypatch.setattr(ollama, "urlopen", lambda *_args, **_kwargs: FakeResponse(raw=b"{not json"))
    adapter = ollama.OllamaAdapter(model="qwen3:8b")
    with pytest.raises(RuntimeError, match="Ollama request failed"):
        adapter.generate("hello")


def test_configured_adapter_surfaces_timeout(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise TimeoutError("timed out")
    monkeypatch.setattr(ollama, "urlopen", timeout)
    adapter = ollama.OllamaAdapter(model="qwen3:8b", timeout=0.2)
    with pytest.raises(RuntimeError, match="timed out"):
        adapter.generate("hello")


def test_configured_adapter_surfaces_model_not_found(monkeypatch):
    def missing_model(*_args, **_kwargs):
        raise HTTPError("http://127.0.0.1:11434/api/chat", 404, "model not found", None, None)
    monkeypatch.setattr(ollama, "urlopen", missing_model)
    adapter = ollama.OllamaAdapter(model="nonexistent-model")
    with pytest.raises(RuntimeError, match="404"):
        adapter.generate("hello")
