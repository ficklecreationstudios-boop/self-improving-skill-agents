"""Optional, explicitly configured Ollama HTTP adapter."""
from __future__ import annotations
import json, os
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

class OllamaAdapter:
    def __init__(self, model: str | None = None, base_url: str | None = None, timeout: float = 60):
        self.model = model or os.getenv("OLLAMA_MODEL")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout = timeout
    @property
    def configured(self) -> bool: return bool(self.model)
    def generate(self, prompt: str) -> str:
        if not self.model:
            return "No Ollama model configured. Set OLLAMA_MODEL to enable local inference. This is a configuration notice, not model-generated advice."
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": False}).encode()
        request = Request(self.base_url + "/api/chat", data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response: payload = json.loads(response.read().decode("utf-8"))
            content = payload.get("message", {}).get("content")
            if not isinstance(content, str): raise RuntimeError("Ollama response missing message.content")
            return content
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
