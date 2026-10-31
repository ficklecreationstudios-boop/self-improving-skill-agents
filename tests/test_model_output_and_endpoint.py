import json
import sys

import pytest

from self_improving_agents import cli, ollama, orchestrator
from self_improving_agents.audit import AuditLedger


# --- F8: the Ollama endpoint stays on this computer unless a remote https server is explicitly allowed ---

@pytest.fixture(autouse=True)
def no_endpoint_environment(monkeypatch):
    for name in ("OLLAMA_BASE_URL", "OLLAMA_ALLOW_REMOTE", "OLLAMA_MODEL", "OLLAMA_TIMEOUT", "OLLAMA_THINK"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def no_network(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("no request may be sent")
    monkeypatch.setattr(ollama, "urlopen", unexpected)


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:11434/", "http://LOCALHOST:11434",
                                 "http://[::1]:11434", "http://127.5.6.7:8080", "https://localhost"])
def test_local_endpoints_are_accepted(url):
    assert ollama.OllamaAdapter(model="m", base_url=url).base_url == url.rstrip("/")


def test_default_endpoint_is_local():
    assert ollama.OllamaAdapter(model="m").base_url == "http://127.0.0.1:11434"


@pytest.mark.parametrize("url", ["http://192.168.1.5:11434", "https://ollama.example.com", "http://10.0.0.2",
                                 "http://127.0.0.1.example.com", "http://0.0.0.0:11434"])
def test_remote_endpoints_are_refused_without_explicit_permission(url, no_network):
    with pytest.raises(ValueError, match="is not on this computer"):
        ollama.OllamaAdapter(model="m", base_url=url)


def test_remote_endpoint_from_the_environment_is_refused(monkeypatch, no_network):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.1.5:11434")
    with pytest.raises(ValueError, match="'192.168.1.5' is not on this computer"):
        ollama.OllamaAdapter()


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "TRUE", " 1"])
def test_only_exactly_1_allows_a_remote_server(monkeypatch, value):
    monkeypatch.setenv("OLLAMA_ALLOW_REMOTE", value)
    with pytest.raises(ValueError, match="is not on this computer"):
        ollama.OllamaAdapter(model="m", base_url="https://ollama.example.com")


def test_allowed_remote_server_must_use_https(monkeypatch):
    monkeypatch.setenv("OLLAMA_ALLOW_REMOTE", "1")
    with pytest.raises(ValueError, match="must use https://"):
        ollama.OllamaAdapter(model="m", base_url="http://ollama.example.com:11434")
    assert ollama.OllamaAdapter(model="m", base_url="https://ollama.example.com").base_url == "https://ollama.example.com"


@pytest.mark.parametrize("url", ["http://user:pw@127.0.0.1:11434", "http://127.0.0.1@evil.example.com",
                                 "http://127.0.0.1:11434?x=1", "http://127.0.0.1:11434#frag"])
def test_credentials_queries_and_fragments_are_refused(url, monkeypatch):
    monkeypatch.setenv("OLLAMA_ALLOW_REMOTE", "1")
    with pytest.raises(ValueError, match="credentials, a query or a fragment"):
        ollama.OllamaAdapter(model="m", base_url=url)


@pytest.mark.parametrize("url", ["ftp://127.0.0.1", "127.0.0.1:11434", "http://", "http://127.0.0.1:99999",
                                 "http://127.0.0.1:port"])
def test_malformed_endpoints_are_refused(url):
    with pytest.raises(ValueError):
        ollama.OllamaAdapter(model="m", base_url=url)


def test_ask_with_a_refused_endpoint_exits_with_one_line_and_writes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OLLAMA_MODEL", "m")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.1.5:11434")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(sys, "argv", ["skill-agents", "ask", "hello", "--skills", str(tmp_path), "--audit", str(audit)])
    with pytest.raises(SystemExit, match="is not on this computer"):
        cli.main()
    assert capsys.readouterr().out == ""


# --- F4: answers are labelled as unverified model output, and no text is returned when no model ran ---

class FakeModel:
    configured = True
    model = "fake-model:1b"

    def generate(self, prompt):
        return "Paris is the capital of France."


def run_ask(tmp_path, monkeypatch, adapter_factory):
    skills = tmp_path / "skills" / "general"; skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nid: general\nname: General\ndomain: general\ntags: [explain]\n---\nBe clear.",
                                     encoding="utf-8")
    audit = tmp_path / "audit.jsonl"
    monkeypatch.setattr(orchestrator, "OllamaAdapter", adapter_factory)
    monkeypatch.setattr(sys, "argv", ["skill-agents", "ask", "Explain the capital of France",
                                      "--skills", str(tmp_path / "skills"), "--audit", str(audit)])
    cli.main()
    return audit


def test_ask_labels_the_answer_as_unverified_model_output(tmp_path, monkeypatch, capsys):
    audit = run_ask(tmp_path, monkeypatch, FakeModel)
    out, err = capsys.readouterr()
    assert "Model output (Ollama model 'fake-model:1b'), not fact-checked:" in err
    answer, _, report = out.partition("\n")
    assert answer == "Paris is the capital of France."
    report = json.loads(report)
    assert report["generated_by"] == {"provider": "ollama", "model": "fake-model:1b"}
    assert report["review"]["verdict"] == "unverified_model_output"
    assert "not fact-checked" in report["review"]["notes"]
    event = AuditLedger(audit)._events()[-1]
    assert event["type"] == "task_completed" and event["payload"]["model"] == "fake-model:1b"
    assert event["payload"]["review_verdict"] == "unverified_model_output"


def test_ask_without_a_model_prints_no_answer(tmp_path, monkeypatch, capsys, no_network):
    with pytest.raises(SystemExit, match="no model inference was performed"):
        run_ask(tmp_path, monkeypatch, lambda: ollama.OllamaAdapter(model=None))
    assert capsys.readouterr().out == ""


def test_generate_without_a_model_never_returns_text(no_network):
    with pytest.raises(RuntimeError, match="no model inference was performed"):
        ollama.OllamaAdapter(model=None).generate("anything")


@pytest.mark.parametrize("stop_reason, labelled", [("final_answer", True), ("step_limit", False)])
def test_agent_labels_only_a_final_answer_as_model_output(tmp_path, monkeypatch, capsys, stop_reason, labelled):
    from types import SimpleNamespace
    result = SimpleNamespace(output="The answer is 391.", tool_calls=(), task_digest="a" * 64,
                             output_digest="b" * 64, steps=0, stop_reason=stop_reason)
    monkeypatch.setattr(cli, "discover_skills", lambda _root: [])
    monkeypatch.setattr(cli, "select_skills", lambda _task, _domain, _skills: [])
    monkeypatch.setattr(cli, "ContainerCapabilityRegistry", lambda _workspace: object())
    monkeypatch.setattr(cli, "OllamaAdapter", FakeModel)
    monkeypatch.setattr(cli, "run_agent_task", lambda *args, **kwargs: result)
    monkeypatch.setattr(sys, "argv", ["skill-agents", "agent", "Add numbers", "--workspace", str(tmp_path),
                                      "--audit", str(tmp_path / "audit.jsonl")])
    if labelled:
        cli.main()
    else:
        with pytest.raises(SystemExit):
            cli.main()
    err = capsys.readouterr().err
    assert ("Model output (Ollama model 'fake-model:1b'), not fact-checked:" in err) is labelled
