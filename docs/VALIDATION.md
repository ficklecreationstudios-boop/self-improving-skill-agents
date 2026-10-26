# Validation record

## Latest baseline CI

- Code commit: `f9059457af966ca0673661f1d6c7784d8a411eb9`
- Workflow: [GitHub Actions run 40347774146](https://github.com/ficklecreationstudios-boop/self-improving-skill-agents/actions/runs/40347774146)
- Matrix: Windows/Linux × Python 3.11/3.14
- Result: all four jobs succeeded; each reported **52 passed, 1 skipped**.
- The single skip is the opt-in live Ollama test. A GitHub-hosted runner cannot access the owner's local Ollama service.

The CI dependency set is pinned in `requirements-test.lock`. A passing matrix establishes only that the checked automated tests passed on those runner environments.

## D2 local Ollama verification

Local evidence recorded from the owner's Windows environment (Python 3.14.8, Ollama 0.40.11, endpoint `http://127.0.0.1:11434`, model `qwen3:8b`):

- Standard regression suite: **53 passed, 3 skipped in 9.12s**.
- Opt-in live Ollama integration test: **1 passed in 21.23s**. This establishes that the configured local model returned non-empty output, not that its answer was correct or safe.
- Repeat opt-in live Ollama integration test: **1 passed in 28.19s**. This repeat also establishes only non-empty output from the configured local model, not answer correctness or safety.
- Focused adapter suite: **9 passed** after adding invalid-JSON, timeout and model-not-found cases.
- Invalid JSON, malformed response shape, HTTP 404/model-not-found, adapter timeout handling, and oversized prompt/output rejection have regression coverage.
- A temporary local HTTP server delayed its response by 1.5 seconds; with a 0.2-second adapter timeout, the adapter raised a timeout error after approximately 0.29 seconds. This validates adapter timeout behavior against that temporary server, not a stalled Ollama inference.
- A request to `http://127.0.0.1:1` with a 2-second timeout failed after approximately 2.09 seconds. The failure surfaced, but this probe did not distinguish connection refusal from timeout.
- A live nonexistent-model request returned HTTP 404/model-not-found. No model was downloaded or changed.

The PowerShell verifier checks that the exact configured model tag exists, installs pinned test dependencies and the editable package, runs the ordinary regression suite with Ollama environment variables temporarily removed, then runs the opt-in live test with the selected model. It restores the previous environment-variable values and presence in a `finally` block.

D2 is marked COMPLETE by the owner based on these bounded local results. It does not establish answer quality, safety, independent evaluation, or release readiness.

## D1 task-lifecycle integration evidence

- Code/test commit: `c4397376b8c33eb82bcadac1aef17165017364e6`
- Workflow: [GitHub Actions run 40377048184](https://github.com/ficklecreationstudios-boop/self-improving-skill-agents/actions/runs/40377048184)
- Result: all four matrix jobs succeeded on Windows/Linux × Python 3.11/3.14.
- Added `tests/test_task_lifecycle.py` to exercise skill selection and prompt construction, generation, basic output review, result delivery, and hash-chain audit verification.
- Failure case: a simulated generation error is recorded as `task_execution_failed` and re-raised.
- Stopped case: an agent that reaches its tool-call step limit records `agent_task_stopped`; the test confirms only the permitted tool call was executed.
- The existing unconfigured-model test confirms a task is recorded as not executed when no model is configured.

These are deterministic integration tests using a fake adapter; they validate orchestration and audit behavior, not live model answer quality or semantic correctness. D1 is marked complete for the stated lifecycle criterion, not as a general safety claim.

## D3 adversarial skill/input regression evidence

- Added `tests/test_prompt_injection_live.py`, an opt-in local-model probe for skill-based instruction override, tool escalation, workspace traversal and canary disclosure. Run it on the owner's machine with `RUN_SECURITY_INTEGRATION=1` and `OLLAMA_MODEL` set to the exact local model tag; GitHub CI skips these live tests by design.
- Added `tests/test_audit_multiprocess.py` to exercise concurrent independent-process audit writers. Its result is pending the integration branch's CI run.

- Code/test commit: `e892608b5117d197bbec50fdffefe3e655460578`
- Workflow: [GitHub Actions run 40377347096](https://github.com/ficklecreationstudios-boop/self-improving-skill-agents/actions/runs/40377347096)
- Result: all four matrix jobs succeeded on Windows/Linux × Python 3.11/3.14.
- Skill discovery resolves and checks containment before reading a file, rejects malformed/duplicate/unknown metadata keys and malformed tags, and rejects skill files larger than 1,000,000 bytes before reading.
- Adversarial fixtures cover workspace traversal, outside-root symlink escape, malformed metadata, oversized skill files, duplicate skill IDs during governance updates, prompt-injection text framed as untrusted context, and oversized Ollama prompts/outputs.

Limitations: the prompt-injection fixture checks framing of untrusted content; it does not prove that a real model will resist every injection. Symlink tests may be skipped on runners where symlink creation is unavailable. D3 remains PARTIAL until prompt-injection behavior and the wider security boundary receive stronger independent evaluation.

## D3–D11 hardening CI evidence

- Integration PR: [#9](https://github.com/ficklecreationstudios-boop/self-improving-skill-agents/pull/9)
- Current CI run: [40388466130](https://github.com/ficklecreationstudios-boop/self-improving-skill-agents/actions/runs/40388466130)
- Matrix: Windows/Linux × Python 3.11/3.14; all four jobs succeeded.
- Each job reported **84 passed, 5 skipped**. The skips include opt-in live Ollama/security tests that cannot access the owner's local model from hosted CI.
- Added multiprocess audit-writer serialization coverage, key-ID-bound HMAC approval signatures, audit-ledger key revocation, candidate holdout preregistration, abstention precision metrics, and stricter malformed capability handling.
- Added [fixed D3–D11 acceptance criteria](ACCEPTANCE_D3_D11.md) and a [clean-machine operations runbook](OPERATIONS_ACCEPTANCE.md).

This CI result does not close D3–D11 by itself. The live prompt-injection suite still requires execution on the owner's local Ollama model; D5 still requires power-loss/filesystem durability testing; D7 requires an owner-approved labeled holdout and independent semantic adjudication; D8 requires OS-level sandbox testing; D9 requires a clean-machine walkthrough; D10 requires externally verified identity/roles; and D11 requires independent review plus explicit owner sign-off. The acceptance checklist intentionally keeps those gates PARTIAL or OPEN until that evidence exists.

## Implemented and tested (baseline code)

- Feedback-to-candidate-to-inert-proposal flow with structural screening and a required regression-case file.
- Bounded allowlisted agent loop; arithmetic and read-only workspace tools only, with path and input bounds.
- HMAC-signed approval artifact workflow; stale proposal rejection; prior-version archives and transaction journal recovery.
- Cross-process audit writer locking, hash-chain validation, and fsync.
- Evaluation CLI that hashes cases, thresholds and skill corpus before running; diagnostic metrics and preregistered thresholds.
- Local Windows Ollama verification script.

## Still not verified / not complete

- Independent held-out quality and safety evaluation with thresholds chosen for the actual deployment risk.
- Robust semantic answer-quality and prompt-injection evaluation. Current phrase-based checks are intentionally limited.
- OS-level sandboxing, independent operator identity/roles, key revocation and external immutable audit storage.
- Power-loss fault injection across every transaction boundary, clean-machine operational walkthrough, and independent security review.

No universal correctness, 100% safety, or production-readiness claim is supported by the current evidence.
