import json
import pytest

from self_improving_agents import ollama


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


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
    from urllib.error import URLError

    def fail(*_args, **_kwargs):
        raise URLError("offline")

    monkeypatch.setattr(ollama, "urlopen", fail)
    adapter = ollama.OllamaAdapter(model="qwen3:8b")
    with pytest.raises(RuntimeError, match="Ollama request failed"):
        adapter.generate("hello")
