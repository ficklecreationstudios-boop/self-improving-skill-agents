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
- Focused adapter suite: **9 passed** after adding invalid-JSON, timeout and model-not-found cases.
- Invalid JSON, malformed response shape, HTTP 404/model-not-found, adapter timeout handling, and oversized prompt/output rejection have regression coverage.
- A temporary local HTTP server delayed its response by 1.5 seconds; with a 0.2-second adapter timeout, the adapter raised a timeout error after approximately 0.29 seconds. This validates adapter timeout behavior against that temporary server, not a stalled Ollama inference.
- A request to `http://127.0.0.1:1` with a 2-second timeout failed after approximately 2.09 seconds. The failure surfaced, but this probe did not distinguish connection refusal from timeout.
- A live nonexistent-model request returned HTTP 404/model-not-found. No model was downloaded or changed.

The PowerShell verifier checks that the exact configured model tag exists, installs pinned test dependencies and the editable package, runs the ordinary regression suite with Ollama environment variables temporarily removed, then runs the opt-in live test with the selected model. It restores the previous environment-variable values and presence in a `finally` block.

D2 is marked COMPLETE by the owner based on these bounded local results. It does not establish answer quality, safety, independent evaluation, or release readiness.

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
