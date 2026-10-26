# Self-Improving Skill-Based Agents

Local-first Python framework for routing tasks to specialist agents, selectively loading skills, reviewing outputs, proposing skill improvements, and requiring human approval before any skill mutation.

## Safety principles
- Standard-library core; Ollama is optional and explicitly configured.
- Skills and task text are untrusted data, never policy or tool permissions.
- Learning produces a proposal only. Applying it requires approval bound to the exact proposal digest.
- Skill updates archive prior versions and emit a hash-chained audit event.
- No shell, arbitrary Python, or host-tool execution is exposed to agents.
- Hash chaining is tamper-evident, not a signature or immutable external storage.

## Quick start (Python 3.11+)
```bash
python -m venv .venv
python -m pip install -e '.[test]'
pytest -q
PYTHONPATH=src python -m self_improving_agents.cli --help
```

Set `OLLAMA_MODEL` and optionally `OLLAMA_BASE_URL` to enable local Ollama inference. No model is downloaded automatically. See `docs/ROADMAP.md` and `SECURITY.md`. This is a development scaffold, not production-ready security software.