"""Optional, explicitly configured Ollama HTTP adapter with bounded input/output."""
from __future__ import annotations
import ipaddress
import json
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

MAX_PROMPT_CHARS = 200_000
MAX_RESPONSE_BYTES = 2_000_000
MAX_OUTPUT_CHARS = 500_000
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_TIMEOUT_SECONDS = 3600.0


_MODEL_UNSET = object()


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _checked_base_url(url: str) -> str:
    """Prompts, skills and workspace text are sent to this server, so it must stay on this computer unless
    the user explicitly allows a remote one, which must then use https."""
    url = url.rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError("OLLAMA_BASE_URL must use http:// or https://")
    if not parts.hostname:
        raise ValueError("OLLAMA_BASE_URL must name a host")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("OLLAMA_BASE_URL must not contain credentials, a query or a fragment")
    parts.port  # raises ValueError for an invalid port
    if not _is_loopback(parts.hostname):
        if os.getenv("OLLAMA_ALLOW_REMOTE") != "1":
            raise ValueError(f"OLLAMA_BASE_URL host {parts.hostname!r} is not on this computer; prompts and file "
                             "contents would leave it. Set OLLAMA_ALLOW_REMOTE=1 to allow a remote server.")
        if parts.scheme != "https":
            raise ValueError("A remote OLLAMA_BASE_URL must use https://")
    return url


def _timeout_from_environment() -> float:
    raw = os.getenv("OLLAMA_TIMEOUT")
    if raw is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        value = float("nan")
    if not 0 < value <= MAX_TIMEOUT_SECONDS:  # also rejects nan and inf
        raise ValueError(f"OLLAMA_TIMEOUT must be a number of seconds in (0, {MAX_TIMEOUT_SECONDS:g}]")
    return value


class OllamaAdapter:
    def __init__(self, model: str | None | object = _MODEL_UNSET,
                 base_url: str | None = None, timeout: float | None = None):
        if timeout is None:
            timeout = _timeout_from_environment()
        if model is _MODEL_UNSET:
            self.model = os.getenv("OLLAMA_MODEL")
        elif model is None or isinstance(model, str):
            self.model = model
        else:
            raise TypeError("model must be a string or None")
        self.base_url = _checked_base_url(base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
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
            # Never return text that could be mistaken for an answer when no model ran.
            raise RuntimeError("No Ollama model configured; no model inference was performed. Set OLLAMA_MODEL.")
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
