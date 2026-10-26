# Validation record

## Latest verified CI

- Code commit: f9059457af966ca0673661f1d6c7784d8a411eb9
- Workflow: [GitHub Actions run 40347774146](https://github.com/ficklecreationstudios-boop/self-improving-skill-agents/actions/runs/40347774146)
- Matrix: Windows/Linux × Python 3.11/3.14
- Result: all four jobs succeeded; each reported **52 passed, 1 skipped**.
- The single skip is the opt-in live Ollama test. The GitHub-hosted runner does not have access to Ollama on the owner's Windows machine.

The CI dependency set is pinned in requirements-test.lock. A passing matrix establishes only that the checked automated tests passed on those runner environments.

## D3 adversarial skill/input regression evidence

- Code/test commit: e892608b5117d197bbec50fdffefe3e655460578
- Workflow: [GitHub Actions run 40377347096](https://github.com/ficklecreationstudios-boop/self-improving-skill-agents/actions/runs/40377347096)
- Result: all four matrix jobs succeeded on Windows/Linux × Python 3.11/3.14.
- Skill discovery now resolves and checks containment before reading a file, rejects malformed/duplicate/unknown metadata keys and malformed tags, and rejects skill files larger than 1,000,000 bytes before reading.
- Adversarial fixtures cover workspace ../ traversal, outside-root symlink escape, malformed metadata, oversized skill files, duplicate skill IDs during governance updates, prompt-injection text framed as untrusted context, and oversized Ollama prompts/outputs.

Limitations: the prompt-injection fixture checks framing of untrusted content; it does not prove that a real model will resist every injection. Symlink tests may be skipped on runners where symlink creation is unavailable. D3 remains PARTIAL until prompt-injection behavior and the wider security boundary receive stronger independent evaluation.

## Implemented and tested

- Feedback-to-candidate-to-inert-proposal flow with structural screening and a required regression-case file.
- Bounded allowlisted agent loop; arithmetic and read-only workspace tools only, with path and input bounds.
- HMAC-signed approval artifact workflow; stale proposal rejection; prior-version archives and transaction journal recovery.
- Cross-process audit writer locking, hash-chain validation, and fsync.
- Evaluation CLI that hashes cases, thresholds and skill corpus before running; diagnostic metrics and preregistered thresholds.
- Local Windows Ollama verification script.

## Still not verified / not complete

- Live inference against the Ollama installation on the owner's Windows machine.
- Independent held-out quality and safety evaluation with thresholds chosen for the actual deployment risk.
- Robust semantic answer-quality and prompt-injection evaluation. Current phrase-based checks are intentionally limited.
- OS-level sandboxing, independent operator identity/roles, key revocation and external immutable audit storage.
- Power-loss fault injection across every transaction boundary, clean-machine operational walkthrough, and independent security review.

No universal correctness, 100% safety, or production-readiness claim is supported by the current evidence.
