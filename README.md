# Self-Improving Skill-Based Agents

Local-first Python framework for routing tasks to specialist agents, selectively loading skills, recording feedback, generating screened skill-update proposals, and requiring approval before any skill mutation.

## Safety principles
- Standard-library core; Ollama is optional and explicitly configured.
- Skills and task text are untrusted data, never policy or tool permissions.
- Feedback-driven learning creates a proposal only. It never applies a candidate automatically.
- Candidate screening checks structure, target identity, size and a narrow known-risk phrase list.
- A required JSONL regression suite tests candidate behavior using deterministic substring assertions. This is not semantic quality validation or a proof of safety.
- Applying a proposal requires explicit approval bound to the exact proposal digest.
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

## Feedback-driven proposal workflow
With a local Ollama model configured, use a frozen JSONL regression case file:

```powershell
skill-agents learn-from-feedback --skill-id software_engineering --task-id task-001 --task "Debug a failing test" --output-text "The previous response missed the root cause" --rating 2 --feedback "Check the actual failure and include a regression test" --holdout eval/my_frozen_cases.jsonl --proposal-output data/proposals/software_engineering.json
```

Each case contains `case_id`, `task`, and optional `must_include` and `must_not_include` string lists. The candidate is run against every case; any failed assertion blocks proposal creation. Freeze the cases before tuning and keep a separate independent holdout. Simple substring checks can be gamed and do not replace human or semantic evaluation.

The active skill remains unchanged. Review the candidate and its audit events, then evaluate it independently before approval.

## Governed skill update workflow
1. Inspect the proposal and its exact digest.
2. Evaluate the candidate on an independent, frozen suite.
3. Only after human review, run `skill-agents apply-proposal data/proposals/software_engineering.json --approver "your review identity" --approve --reason "review rationale"`.
4. Verify the audit with `skill-agents verify-audit`.

`--approver` is a self-asserted label, not cryptographic identity. Do not use this as an authorization boundary against a hostile local user.

See `docs/DONE_CRITERIA.md`, `docs/ROADMAP.md`, and `SECURITY.md`. This remains a development system, not production-ready security software.
