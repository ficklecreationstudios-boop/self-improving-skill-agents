# Self-Improving Skill-Based Agents

Local-first Python framework for routing tasks to specialist agents, selectively loading skills, recording feedback, generating screened skill-update proposals, and requiring signed approval before any skill mutation.

## Safety principles
- Standard-library core; Ollama is optional and explicitly configured.
- Skills and task text are untrusted data, never policy or tool permissions.
- If no model is configured, a task is audited as not executed; a configuration notice is never misrepresented as a model answer.
- Feedback-driven learning creates a proposal only. It never applies a candidate automatically.
- Candidate screening checks structure, target identity, size and a narrow known-risk phrase list.
- Required JSONL regression cases use substring assertions; this is not semantic quality validation or proof of safety.
- Updates require an HMAC-SHA256 approval signature bound to the exact proposal digest. HMAC proves possession of a shared secret, not a real-world identity.
- Keep approval keys outside the repository, protect access, and do not commit keys or signed approval artifacts.
- Skill updates archive prior content, journal transaction state, and write a hash-chained audit event. `skill-agents recover` reconciles incomplete journaled updates.
- Audit writes are serialized with a cross-process lock and fsync. Hash chaining is tamper-evident, not immutable external storage.
- No shell, arbitrary Python, or host-tool execution is exposed to agents.

## Quick start
```bash
python -m venv .venv
python -m pip install -e '.[test]'
pytest -q
PYTHONPATH=src python -m self_improving_agents.cli --help
```

## Approval-key workflow
Create a random key file once and protect it outside version control:
```powershell
skill-agents init-approval-key "$HOME\skill-agents.approval-key"
```
Create and review a proposal, then sign it as a separate explicit step:
```powershell
skill-agents approve-proposal data/proposals/software_engineering.json --key-file "$HOME\skill-agents.approval-key" --approver "reviewer-id" --reason "reviewed candidate and test evidence" --approve --approval-output data/approvals/software_engineering.json
skill-agents apply-proposal data/proposals/software_engineering.json data/approvals/software_engineering.json --key-file "$HOME\skill-agents.approval-key"
skill-agents verify-audit
skill-agents recover
```
The approval file is sensitive governance evidence and should not be committed publicly. Anyone with the key can sign approvals; use OS account permissions or a dedicated signing service for stronger identity controls.

## Feedback-driven proposal workflow
With a local Ollama model configured, use a frozen JSONL regression case file:
```powershell
skill-agents learn-from-feedback --skill-id software_engineering --task-id task-001 --task "Debug a failing test" --output-text "The previous response missed the root cause" --rating 2 --feedback "Check the actual failure and include a regression test" --holdout eval/my_frozen_cases.jsonl --proposal-output data/proposals/software_engineering.json
```
Each case contains `case_id`, `task`, and optional `must_include` and `must_not_include` string lists. Every case is run against the candidate; any failed assertion blocks proposal creation. Freeze cases before tuning and keep a separate independent holdout. Simple substring checks can be gamed and do not replace human or semantic evaluation.

The active skill remains unchanged. Review the candidate and its audit events, then evaluate it independently before signing approval.

## Live local-model test
On the machine running Ollama, set `OLLAMA_MODEL` and run `RUN_OLLAMA_INTEGRATION=1 pytest -q tests/test_ollama_live.py`. This is deliberately opt-in; CI does not claim to have tested your local model.

See `docs/DONE_CRITERIA.md`, `docs/ROADMAP.md`, and `SECURITY.md`. This remains a development system, not production-ready security software.
