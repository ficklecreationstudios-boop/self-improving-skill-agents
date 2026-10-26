"""Optional, explicitly configured Ollama HTTP adapter with bounded input/output."""
from __future__ import annotations
import json
import os
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

MAX_PROMPT_CHARS = 200_000
MAX_RESPONSE_BYTES = 2_000_000
MAX_OUTPUT_CHARS = 500_000


class OllamaAdapter:
    def __init__(self, model: str | None = None, base_url: str | None = None, timeout: float = 60):
        self.model = model or os.getenv("OLLAMA_MODEL")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("OLLAMA_BASE_URL must use http:// or https://")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.model)

    def generate(self, prompt: str) -> str:
        if not self.model:
            return "No Ollama model configured. Set OLLAMA_MODEL to enable local inference. This is a configuration notice, not model-generated advice."
        if not isinstance(prompt, str) or len(prompt) > MAX_PROMPT_CHARS:
            raise RuntimeError(f"Ollama prompt exceeds {MAX_PROMPT_CHARS}-character limit")
        body = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}],
                           "stream": False}).encode("utf-8")
        request = Request(self.base_url + "/api/chat", data=body,
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise RuntimeError(f"Ollama response exceeds {MAX_RESPONSE_BYTES}-byte limit")
            payload = json.loads(raw.decode("utf-8"))
            content = payload.get("message", {}).get("content")
            if not isinstance(content, str):
                raise RuntimeError("Ollama response missing message.content")
            if len(content) > MAX_OUTPUT_CHARS:
                raise RuntimeError(f"Ollama output exceeds {MAX_OUTPUT_CHARS}-character limit")
            return content
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
