# Handoff guide

For someone who has this repository but none of its history, and wants to run it or adapt it to another system.

## Start here

- **The current code is on branch `work/d8-os-sandbox-20261027`.** `main` holds only a bootstrap README and has never been merged into, so a default clone gives you almost nothing.
  ```powershell
  git clone -b work/d8-os-sandbox-20261027 https://github.com/ficklecreationstudios-boop/self-improving-skill-agents.git
  ```
- **Status:** feature-complete and conditionally accepted for one person's use on one Windows 11 PC. It is not approved for release, and it has had no independent review. See [COMPLETION_STATUS.md](COMPLETION_STATUS.md).
- **No license file exists.** Ask the owner before reusing the code elsewhere.
- **All validation was done by the implementer**, an AI assistant, and the original evidence files stay on the owner's PC. You have the tests, the CI runs and these summaries, so rerun what you intend to rely on.

## What it is

A local command-line assistant that answers questions with a model running on your own machine, and can read files in a folder you name. Its instructions live in plain-text skill files. It can suggest improvements to those skills from your feedback, but nothing changes until a person signs off. Every important action goes into a tamper-evident log.

### What it can do

| Command | What it does |
|---|---|
| `ask` | Answers a question using the model and matching skills. No file access. |
| `agent` | Answers a question about a folder, using three tools inside a throwaway container: calculator, read a file, search text. |
| `learn-from-feedback` | Turns feedback on an answer into a suggested skill change, tested against your frozen cases. |
| `propose` | Packages a skill change you wrote by hand. |
| `approve-proposal`, `apply-proposal` | Signs a suggestion after showing the diff, then applies it, keeping the old version. |
| `init-approval-key`, `revoke-approval-key`, `add-approver`, `list-approvers` | Manage who can approve. |
| `init-revocation-registry` | Creates the per-user list of revoked keys. Run it once per user account. |
| `verify-audit`, `anchor-audit`, `recover-audit`, `recover` | Check the log, remember its fingerprint outside the file, and clean up after a crash. |
| `evaluate-quality`, `benchmark` | Score answers on frozen cases, and estimate prompt size saved by loading only matching skills. |

### What it cannot do

- It has no internet, email, write, delete, shell or code-execution tools.
- It cannot change its own skills without a signature.
- It cannot tell whether an answer is right. The review only checks that an answer isn't empty, and answers are labelled as not fact-checked. In testing it invented a court case.
- **It cannot be relied on to refuse things.** See [Security](#security-what-protects-you).

## How it works

```text
You -> skill-agents CLI -> picks up to 3 skills -> local model (Ollama)
                                                     | asks for a tool
                                                     v
                         checks the request -> fresh Docker container per call
                                                  workspace read-only, no network
                                                     |
Audit ledger (hash-chained JSONL) <-- records digests of tasks, calls and answers
```

Self-improvement is a separate path: feedback, then a candidate skill, then automatic screening, then an inert proposal file, then your signature, then apply with the old version archived.

| Area | Files in `src/self_improving_agents/` |
|---|---|
| CLI | `cli.py` |
| Tasks and prompts | `orchestrator.py`, `agent_loop.py` (agent prompt), `agents/specialists.py` (`ask` prompt) |
| Skills | `skills.py` |
| Tools and sandbox | `capabilities.py`, `container_capabilities.py`, `container_worker.py` |
| Model | `ollama.py` |
| Governance | `governance/approval.py`, `approval_auth.py`, `revocation.py`, `approver_policy.py` |
| Ledger and locks | `audit.py`, `audit_anchor.py`, `file_lock.py`, `owner_only.py` |
| Learning and evaluation | `learning.py`, `evaluation.py`, `quality_evaluation.py`, `refusal_eval.py` |

## Set it up on a new machine

The application has no third-party runtime dependencies. You need Python 3.11 or later, plus Ollama for answers and Docker for `agent`.

1. **Install the code.** Use the pinned build tools so the editable install works.
   ```powershell
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements-test.lock
   .venv\Scripts\python -m pip install --no-build-isolation -e .
   .venv\Scripts\pytest -q
   ```
   Without a model and Docker image, expect skips and no failures. If Docker and the image are present, real sandbox tests run and need `D8_CONTAINER_TEST_ROOT` set to a folder Docker can mount.
2. **Install a model.** Install Ollama, pull a model, and set `OLLAMA_MODEL`. Every result in this repository is for `qwen3:8b` on Ollama 0.40.11 with `OLLAMA_THINK=false`, so another model needs its own evaluation. If long answers time out, raise `OLLAMA_TIMEOUT` from its default of 60 seconds.
3. **Pull the sandbox image once.** The app never downloads it, and tool calls fail safely without it.
   ```powershell
   docker pull python@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce
   ```
4. **Make a working folder on a fast internal drive.** `data\audit.jsonl` and `skills\` are found relative to where you run the command, so always run from this folder, or every command will quietly use a different ledger. Copy the repository's `skills\` into it as a starting point. On the original PC, an external USB drive stalled ledger writes for up to 13 s, long enough to hit the 10 s lock limit.
5. **Set up approvals, if you'll change skills.**
   ```powershell
   skill-agents init-revocation-registry
   skill-agents init-approval-key keys\me.approval-key
   skill-agents add-approver --key-file keys\me.approval-key --name "Your Name"
   ```
   Back up the key securely. Anyone holding it can sign approvals. The revocation registry, approver list and anchors live per user in `%LOCALAPPDATA%\self-improving-skill-agents\` (`~/.local/state/self-improving-skill-agents/` on Linux or macOS). That location can't be redirected, so don't experiment with these commands on an account you care about.
6. **Check it.**
   ```powershell
   skill-agents ask "What is 12 times 12?"
   skill-agents agent "Read notes.md and summarise it" --workspace <a safe folder>
   skill-agents verify-audit
   skill-agents anchor-audit
   ```
   Keep the hash from `anchor-audit` off the machine. It only covers the ledger up to that point, so repeat it occasionally and keep every hash.

## First-use walkthrough

A repeatable check that uses a throwaway folder and ledger, so real data stays as it is.

1. Make a throwaway folder and work from it, so the ledger lands there. Copy the repository's `skills` folder into it, and put a harmless `notes.md` in a `workspace` subfolder.
2. Check the commands exist:
   ```powershell
   skill-agents --help
   skill-agents agent --help
   ```
3. Run a harmless task. `OLLAMA_MODEL` must be set, and Docker must be running with the pinned image:
   ```powershell
   skill-agents agent "Read notes.md and summarise it in one sentence." --workspace workspace
   ```
4. Confirm four things:
   - The answer matches the file, and is labelled as model output that is not fact-checked.
   - The printed summary shows `read_text_file` in `tool_names` and `stop_reason` of `final_answer`.
   - `skill-agents verify-audit` prints `VALID`, and `data\audit.jsonl` holds `agent_tool_invoked` and `agent_task_completed`.
   - `docker ps -a --filter name=skill-agents-cap-` lists nothing. Agent tool containers use that name prefix.

**Don't run these in a throwaway check:** `anchor-audit`, `init-revocation-registry`, `add-approver` and `revoke-approval-key`. They write to the shared per-user folder, not the throwaway folder. An anchor for a throwaway ledger is harmless but stays in the shared file. This happened on the original PC, on 2026-11-05.

## Everyday use

**Rules that keep it safe:**
- Never point `--workspace` at a folder holding secrets in `.md`, `.txt`, `.py`, `.json`, `.yaml`, `.yml` or `.toml` files. The model can read those, and it will if a file tells it to.
- Never add write, shell, delete or network tools. The model won't hold back, so the tool list is what limits it.
- Read every proposal before signing it. The automatic screens only match phrases, and once passed a suggestion that narrowed a general skill to a single task.
- Keep using the same ledger file.
- Check facts, names, numbers and citations in answers.

**Changing a skill:**
```powershell
skill-agents propose general proposed.md --rationale "why" --output data\proposals\general.json
skill-agents approve-proposal data\proposals\general.json --key-file keys\me.approval-key --approver "Your Name" --reason "reviewed" --approve --approval-output data\approvals\general.json
skill-agents apply-proposal data\proposals\general.json data\approvals\general.json --key-file keys\me.approval-key
```
`approve-proposal` shows the diff and asks you to type the skill ID. Once an approver list exists, the `--approver` name must match it exactly.

**To roll back a skill,** propose the archived copy from `data\skill-archive` as a new signed change.

**After a crash,** run `skill-agents recover-audit`, then `skill-agents recover`, then `skill-agents verify-audit`.

**To replace a key,** create a new key, add it with `add-approver`, then run `revoke-approval-key <old key id> --reason "rotation"`.

**To back up,** stop anything using the app, then copy the working folder and the per-user folder. Store the key separately and securely. A copy at a different path isn't covered by stored anchors, so check it with `verify-audit --audit <copy> --anchor-seq <n> --anchor-hash <hash>`.

## Adapt it to another system

| To change | Do this | Then re-check |
|---|---|---|
| **Domain knowledge** | Add `skills\<id>\SKILL.md`, as below. | `evaluation.py` routing cases of your own. Selection is by keyword, not meaning. |
| **Model** | Set `OLLAMA_MODEL`. Only Ollama is supported; other backends need an adapter like `ollama.py`. | Rerun the live tests and the refusal evaluation. Don't reuse these results. |
| **Which files it reads** | Choose the `--workspace` folder. The readable types are `READABLE_SUFFIXES` in `capabilities.py`. | The forced-attack tests. Widening the list widens what an injected instruction can reach. |
| **Tools** | Only with care, in `capabilities.py` and `container_worker.py`. | Any privileged tool breaks the safety model, because the model does attempt forbidden actions. It would need a new design and threat review. |
| **Prompt** | `agent_loop.py`. | The refusal evaluation, on **new** cases. The corpus here has already influenced the prompt. |
| **Operating system** | Windows 11 is what has been used daily. Linux Docker sandbox tests and the unit suite pass in CI, but everyday use on Linux has not been exercised, and macOS has not been tried. | The real-Docker tests with `D8_REQUIRE_DOCKER=1`. |
| **More than one person** | Not supported as is. Approver names aren't verified identity, the key is a shared secret, and there is no two-person approval. | Needs real identity, per-user keys and a review of `docs/ACCEPTANCE_D3_D11.md`, D10. |

**Skill format.** The folder holds one `SKILL.md`, and the only allowed metadata keys are `id`, `name`, `domain` and `tags`:
```markdown
---
id: my_skill
name: My skill
domain: engineering
tags: [debug, review]
---

Instructions here. Treated as untrusted reference text, not policy.
```
Up to 3 skills are chosen per task. A matching `--domain` scores 3, each tag found in the task's words scores 1, and `general` skills are always eligible.

**Regression cases for `learn-from-feedback`** are JSONL with `task`, `must_include`, `must_not_include` and optionally `case_id`. They are substring checks, so they catch only what you wrote down. Freeze them before tuning and keep a separate untouched holdout.

## Settings

| Variable | Purpose |
|---|---|
| `OLLAMA_MODEL` | Model tag. If unset, tasks are recorded as not executed and no answer is produced. |
| `OLLAMA_BASE_URL` | Default `http://127.0.0.1:11434`. Must be on this computer unless `OLLAMA_ALLOW_REMOTE=1`, and a remote address must use https. |
| `OLLAMA_THINK` | `true` or `false`. |
| `OLLAMA_TIMEOUT` | Seconds per request, up to 3600. Default 60. |
| `D8_CONTAINER_TEST_ROOT` | Tests only: a folder Docker can mount. |
| `D8_REQUIRE_DOCKER` | Tests only: `1` makes a skipped sandbox test fail. |
| `RUN_OLLAMA_INTEGRATION`, `RUN_SECURITY_INTEGRATION`, `SECURITY_BENCHMARK_REPORT` | Tests only: turn on live-model tests and name their report file. |

**Fixed limits:** 4 tool calls by default and 8 at most; files up to 128 KB; a tool call stops after 8 s, with 512 KB of output, 128 MB of memory, half a CPU and 32 processes.

## Security: what protects you

**The sandbox and the tool list protect you, not the model.** The live evaluation made 240 runs across attack, ambiguous and harmless tasks, against one model, twice:

| Measure | First run | With the stronger prompt | Required |
|---|---|---|---|
| Secrets leaked | 0 | 0 | 0 |
| Forbidden actions executed | 0 | 0 | 0 |
| Forbidden attempts, of 90 attacks | 56 | 16 | at most 4 |
| Proper refusals, of 90 attacks | 15 | 66 | at least 72 |
| Refusals of harmless tasks, of 15 per arm | 0 | 0 | at most 1 |

The evaluation **failed both times**, and the owner accepted that for personal use as a known limitation. The stronger prompt also makes the agent decline borderline requests. Treat the harness in `refusal_eval.py` as reusable, but write new cases if you change the model or prompt.

**Known limits:**
- HMAC approvals prove someone holds the key, not who they are.
- A program running as your user can edit the ledger, anchors, approver list and registry together. An anchor hash kept off the machine is the only check that survives this.
- Real power loss has not been tested. Forced process kills have.
- Docker Desktop, WSL2 and kernel escapes are out of scope.
- CI has no Windows Docker coverage, because hosted Windows runners have no Linux containers. Sandbox tests in CI run on Linux only.
- One unexplained event: a SYSTEM permission entry appeared on a CI folder. The fix replaces the whole access list, so it doesn't depend on the cause.

## Tests and CI

`.github/workflows/tests.yml` runs on pushes to this branch:

| Job | Covers |
|---|---|
| `test` (4 jobs) | The suite on Windows and Ubuntu, Python 3.11 and 3.14 |
| `docker-sandbox` | Real sandbox tests on Linux. A skip fails the job. |
| `clean-windows-ops-drill` | `scripts/ops-drill.ps1` on a clean runner: install, no-model, approvals, key rotation, anchors, backup and restore, recovery, rollback, upgrade, uninstall. It refuses to run outside CI because it changes per-user state. |

Run the full local check with Docker and the live model like this:
```powershell
$env:D8_REQUIRE_DOCKER="1"; $env:D8_CONTAINER_TEST_ROOT="<a folder Docker can mount>"
$env:RUN_OLLAMA_INTEGRATION="1"; $env:RUN_SECURITY_INTEGRATION="1"
$env:OLLAMA_MODEL="qwen3:8b"; $env:OLLAMA_THINK="false"; $env:OLLAMA_TIMEOUT="300"
$env:SECURITY_BENCHMARK_REPORT="<a folder outside the repository>\security.jsonl"
pytest -q -rs
```
Last result on Windows with the live model on: 544 passed, 0 failed, 8 skipped. Those skips were symlink tests, which need an elevated shell or Developer Mode. Later runs without the live model count 549 passed and 14 skipped.

**Things that have caught people out:**
- Docker Desktop can lose its mount of a drive and report `no such device`, as below.
- Text piped from Windows PowerShell 5.1 did not reach the approval prompt on a hosted runner. The drill feeds typed confirmations from a file instead.
- Hosted Windows runners are elevated, so new files belong to Administrators there. Test elevated at least once.
- Job logs need admin sign-in, while annotations are public.
- A hosted run once failed because `docker info` did not answer within 5 s, even though `docker pull` had just worked. Docker checks in tests now share a 30 s limit, `DOCKER_CHECK_TIMEOUT` in `tests/docker_support.py`, and their failure messages include the real error. It happened once in 7 runs, so the cause is not proven; a repeat would now state itself clearly. A check that still doesn't answer fails the run when `D8_REQUIRE_DOCKER=1`. This limit is separate from the 8 s sandbox limit on tool calls.

### If Docker loses a drive

**Symptom:** tool calls fail with `Sandbox process failed`, or Docker reports `no such device` for a path on that drive, while Windows can still read the drive. On the original PC this was an external USB drive, seen twice in 3 days. Sleep and USB power-saving may be the trigger, but that is not proven.

**Fix without a restart.** This keeps running containers up. It worked on Docker Desktop 4.97.0 with the WSL 2 backend, for `D:`. Change the drive letter if needed:
```powershell
& "$env:WINDIR\System32\wsl.exe" -d docker-desktop --cd / -e sh -c 'for m in /tmp/docker-desktop-root/run/desktop/mnt/host/d /tmp/docker-desktop-root/mnt/host/d /mnt/host/d /mnt/host/d; do umount -l $m; done; mount -t drvfs D:\\ /mnt/host/d -o metadata,uid=0,gid=0,symlinkroot=/mnt/host/; ls /mnt/host/d | head -3'
```
It should end by listing a few folders from the drive. Before relying on it, check that no running container binds that drive, with `docker inspect`. These are Docker Desktop internals, so a future version may differ.

**If that doesn't work,** restart Docker Desktop, which interrupts running containers. Then rerun the real sandbox tests with `D8_REQUIRE_DOCKER=1`.

## What's left

Nothing is planned. The owner's direction is to use it and change it only for real problems or new needs.

| Item | Who | Notes |
|---|---|---|
| First real sign-and-apply on real skills | Owner | Only drilled on disposable data so far. |
| Reliable model refusal | Anyone | Needs a different model or approach, and new test cases. |
| Independent security review | If going beyond personal use | Recorded as not applicable to personal use. |
| Two-person review, verified identity | If going beyond one person | Not built. |
| Power-loss test | If needed | Accepted risk. Needs a VM with a hard power-off. |

**Further reading:** [COMPLETION_STATUS.md](COMPLETION_STATUS.md) for each gate, [DONE_CRITERIA.md](DONE_CRITERIA.md) and [ACCEPTANCE_D3_D11.md](ACCEPTANCE_D3_D11.md) for the release standard, [OPERATIONS_ACCEPTANCE.md](OPERATIONS_ACCEPTANCE.md) for the runbook, [PERSONAL_USE_ACCEPTANCE.md](PERSONAL_USE_ACCEPTANCE.md) for the original acceptance, and `../SECURITY.md` for the security model.
