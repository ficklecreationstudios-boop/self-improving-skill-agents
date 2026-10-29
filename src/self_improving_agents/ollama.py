"""Optional, explicitly configured Ollama HTTP adapter with bounded input/output."""
from __future__ import annotations
import json
import os
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

MAX_PROMPT_CHARS = 200_000
MAX_RESPONSE_BYTES = 2_000_000
MAX_OUTPUT_CHARS = 500_000


_MODEL_UNSET = object()


class OllamaAdapter:
    def __init__(self, model: str | None | object = _MODEL_UNSET,
                 base_url: str | None = None, timeout: float = 60):
        if model is _MODEL_UNSET:
            self.model = os.getenv("OLLAMA_MODEL")
        elif model is None or isinstance(model, str):
            self.model = model
        else:
            raise TypeError("model must be a string or None")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("OLLAMA_BASE_URL must use http:// or https://")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout
        raw_think = os.getenv("OLLAMA_THINK")
        if raw_think is None:
            self.think = None
        elif raw_think == "true":
            self.think = True
        elif raw_think == "false":
            self.think = False
        else:
            raise ValueError(
                "OLLAMA_THINK must be exactly 'true' or 'false' when set"
            )

    @property
    def configured(self) -> bool:
        return bool(self.model)

    def generate(self, prompt: str) -> str:
        if not self.model:
            return "No Ollama model configured. Set OLLAMA_MODEL to enable local inference. This is a configuration notice, not model-generated advice."
        if not isinstance(prompt, str) or len(prompt) > MAX_PROMPT_CHARS:
            raise RuntimeError(f"Ollama prompt exceeds {MAX_PROMPT_CHARS}-character limit")
        request_payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        if self.think is not None:
            request_payload["think"] = self.think
        body = json.dumps(request_payload).encode("utf-8")
        request = Request(self.base_url + "/api/chat", data=body,
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise RuntimeError(f"Ollama response exceeds {MAX_RESPONSE_BYTES}-byte limit")
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("Ollama response must be a JSON object")
            if payload.get("done_reason") == "length":
                raise RuntimeError("Ollama generation truncated: done_reason=length")
            message = payload.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str):
                raise RuntimeError("Ollama response missing message.content")
            if not content.strip():
                raise RuntimeError("Ollama response content is empty")
            if len(content) > MAX_OUTPUT_CHARS:
                raise RuntimeError(f"Ollama output exceeds {MAX_OUTPUT_CHARS}-character limit")
            return content
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
