# Self-Improving Skill-Based Agents

Local-first Python framework for routing tasks to specialist agents, selectively loading skills, running a bounded allowlisted tool loop, recording feedback, generating screened skill-update proposals, and requiring signed approval before any skill mutation.

## Safety principles
- Standard-library runtime; Ollama is optional and explicitly configured.
- Skills, tasks, feedback, files and tool results are untrusted data.
- If no model is configured, a task is audited as not executed; a configuration notice is never misrepresented as a model answer.
- The optional agent loop exposes only a bounded calculator and read-only workspace file/search capabilities. No shell, network, write, delete, or arbitrary code execution is exposed.
- Feedback-driven learning creates a proposal only. It never applies a candidate automatically.
- Required JSONL regression cases use substring assertions; this is not semantic quality validation or proof of safety.
- Updates require an HMAC-SHA256 approval signature bound to the exact proposal digest. HMAC proves possession of a shared secret, not a real-world identity.
- Keep approval keys outside the repository and protect access.
- Skill updates archive prior content, journal transaction state, and write a hash-chained audit event. `skill-agents recover` reconciles interrupted updates.
- Audit writes are serialized with a cross-process lock and fsync. Hash chaining is tamper-evident, not immutable external storage.

## Reproducible test setup
```powershell
python -m pip install -r requirements-test.lock
python -m pip install --no-build-isolation -e .
pytest -q
```
The CI test/build dependency set is pinned in `requirements-test.lock`.

## Bounded tool agent
```powershell
skill-agents agent "Find where this project defines its audit event format" --workspace . --skills skills --max-steps 4
```
It uses selected skill references and only the allowlisted calculator, read-only file reader, and workspace search. `--workspace` is required.

The file reader and search open only `.md`, `.txt`, `.py`, `.json`, `.yaml`, `.yml` and `.toml` files, judged by the resolved target, so a symlink cannot alias a disallowed file. Other workspace files, such as `.env`, `.pem` or files with no extension, are not readable. This is not secret protection: anything stored in an allowed file type inside the workspace can be read and passed to the model, so do not point `--workspace` at a directory holding secrets in such files.

Each tool call runs in a short-lived Docker container from a digest-pinned image: workspace mounted read-only, no network, read-only root filesystem, all capabilities dropped, `no-new-privileges`, a non-root user, and pids/memory/CPU limits. If Docker or the pinned image is unavailable, the tool call fails closed; it never falls back to running on the host. The image is never downloaded automatically (`--pull never`), so pull it once with the command below. The command exits non-zero if the agent stops without a valid final answer.

**Verified scope:** this container sandbox has been exercised on one Windows host only. It has not been independently reviewed, and Linux sandbox verification is not yet supported. See `docs/ACCEPTANCE_D3_D11.md` for open items.

Prerequisite: Docker Engine and the pinned image:
```powershell
docker pull python@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce
```

## Quality evaluation
Freeze a JSONL dataset and a JSON threshold file *before* running the evaluation. Cases may contain `task`, `domain`, `must_include`, `must_not_include`, `expected_abstain`, and `expected_skill_id`. The threshold file sets one or more values between 0 and 1, e.g. `{"minimum_execution_success_rate": 0.99, "maximum_forbidden_phrase_violation_rate": 0.0}` (illustrative only; set thresholds for the actual risk before testing).
```powershell
skill-agents evaluate-quality --cases eval/my_frozen_cases.jsonl --thresholds eval/my_preregistered_thresholds.json --skills skills --audit data/evaluation-audit.jsonl --output data/reports/evaluation.json
```
The dataset and threshold-file hashes are written to the audit ledger before inference. The scorer reports execution, phrase, routing-label, and abstention-marker metrics. These are diagnostics, not semantic correctness or safety proof. Keep a separate untouched holdout for final evaluation.

## Approval-key workflow
Create a random key file once and protect it outside version control. `init-approval-key` restricts the new file to the current user: mode 0600 on POSIX, and on Windows a single full-control entry for the current user's SID, with inheritance removed. If that restriction fails, no key is created.
```powershell
skill-agents init-approval-key "$HOME\skill-agents.approval-key"
```
Create the per-user revocation registry once. It lives at a fixed place, `%LOCALAPPDATA%\self-improving-skill-agents\approval-key-revocations.json` on Windows (`~/.local/state/self-improving-skill-agents/` on POSIX). The location comes from the OS profile, and no option or environment variable changes it. Only the current user can open it. If you have revoked keys before, import every audit ledger that recorded them:
```powershell
skill-agents init-revocation-registry --import-audit data/audit.jsonl
```
Signing, applying and revoking all fail closed if the registry is missing, unreadable, corrupt or not owner-only. It is never created or reset automatically; `init-revocation-registry` refuses to overwrite an existing registry. Its digest catches accidental corruption, not deliberate edits by someone who can already write files as you.
Then explicitly sign and apply a reviewed proposal:
```powershell
skill-agents approve-proposal data/proposals/software_engineering.json --key-file "$HOME\skill-agents.approval-key" --approver "reviewer-id" --reason "reviewed candidate and test evidence" --approve --approval-output data/approvals/software_engineering.json
skill-agents apply-proposal data/proposals/software_engineering.json data/approvals/software_engineering.json --key-file "$HOME\skill-agents.approval-key"
skill-agents verify-audit
skill-agents recover
```
Before signing, `approve-proposal` first refuses a revoked key, or a stale proposal whose skill has changed since the proposal was made. Otherwise it prints the current skill, the proposed replacement and a line diff. Control and invisible formatting characters, such as terminal escape sequences and bidirectional overrides, are shown as `\uXXXX` so they cannot hide or rewrite what you see. Then it asks you to type the exact skill ID. Anything else, including an empty answer or end of input, cancels without signing. The skill is checked again after you confirm. Pass the same `--skills`, `--archive` and `--audit` values to `approve-proposal` and `apply-proposal`. The prompt reads standard input, so piping the skill ID in skips the reading but not the record of what was signed.
Anyone with the key can sign approvals; the approver label is not independently verified identity. Key IDs are printed by `init-approval-key`. Revoke a key with `skill-agents revoke-approval-key <key-id> --reason "key rotation" --audit data/audit.jsonl`. This records the key ID in the per-user registry first, then in the audit ledger. Signing and applying check both, so a revoked key stays revoked whichever ledger file is used. `apply-proposal` also requires a matching approval-signed record in the ledger it is given, so sign and apply with the same `--audit` file. Keep the replacement key outside the repository and use OS account permissions or a dedicated signing service for stronger identity controls.

## Feedback-driven proposal workflow
With a local Ollama model configured, use a frozen JSONL regression case file:
```powershell
skill-agents learn-from-feedback --skill-id software_engineering --task-id task-001 --task "Debug a failing test" --output-text "The previous response missed the root cause" --rating 2 --feedback "Check the actual failure and include a regression test" --holdout eval/my_frozen_cases.jsonl --proposal-output data/proposals/software_engineering.json
```
Every case is run against the candidate; any failed substring assertion blocks proposal creation. Freeze cases before tuning and keep a separate independent holdout.

## Model settings
- `OLLAMA_MODEL`: the local model tag. If it isn't set, tasks are audited as not executed.
- `OLLAMA_BASE_URL`: default `http://127.0.0.1:11434`.
- `OLLAMA_THINK`: exactly `true` or `false` when set.
- `OLLAMA_TIMEOUT`: seconds per model request, from 0 (exclusive) to 3600; default `60`. Raise it when long answers time out on slower hardware. For example, `qwen3:8b` split between the CPU and a 6 GB GPU needed more than 60 s for some long answers.

## Verify Ollama on Windows
The GitHub runner cannot access Ollama on your PC. Activate the project venv, set `OLLAMA_MODEL` to an installed local tag, and run `./scripts/verify-local-ollama.ps1`. See `docs/LOCAL_OLLAMA_VERIFICATION.md`. The script does not download a model or change active skills.

To run the opt-in prompt-injection benchmark against that exact local model, set `RUN_SECURITY_INTEGRATION=1` and `SECURITY_BENCHMARK_REPORT` to an absolute JSONL path outside the repository, then run `python -m pytest -q tests/test_prompt_injection_live.py`. The report contains model digest and evidence hashes, not raw outputs. This finite test corpus is not a universal safety proof.

See `docs/DONE_CRITERIA.md`, `docs/ROADMAP.md`, and `SECURITY.md`. This remains a development system, not production-ready security software.
