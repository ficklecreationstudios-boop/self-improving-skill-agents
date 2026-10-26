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

## Optional local Ollama
Set `OLLAMA_MODEL` and optionally `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`). No model is downloaded automatically. Without a model configured, `ask` reports that inference is not configured instead of pretending a local model answered.

## Governed skill update workflow
1. Edit a proposed complete skill file separately; the existing skill is not changed.
2. Run `skill-agents propose software_engineering proposed_SKILL.md --rationale "Describe the evidence"`.
3. Review the JSON proposal and exact digest.
4. Only after human review, run `skill-agents apply-proposal data/proposals/software_engineering.json --approver "your review identity" --approve --reason "review rationale"`.
5. Verify the audit with `skill-agents verify-audit`.

`--approver` is a self-asserted label, not cryptographic identity. Do not use this as an authorization boundary against a hostile local user.

## P0–P5 scope
- P0 foundation: records, CLI, audit, tests.
- P1 skill discovery and selective retrieval with safe path resolution.
- P2 explicit Ollama adapter, execution provenance, basic review.
- P3 proposal creation is separate from task execution and cannot mutate skills directly.
- P4 exact-digest approval, stale-base recheck, archived updates, audit trail.
- P5 regression tests and a rough context-size proxy (not a tokenizer benchmark).

This is a development scaffold, not production-ready security software. See `docs/ROADMAP.md` and `SECURITY.md`.
