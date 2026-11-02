# Security model

Task text, feedback, skill files, repository documents, workspace files, and tool results are untrusted input. The optional agent loop exposes only three allowlisted capabilities: bounded arithmetic, UTF-8 file reads inside a configured workspace, and text search inside that workspace. Reads and searches are limited to `.md`, `.txt`, `.py`, `.json`, `.yaml`, `.yml` and `.toml` files, checked on the resolved target; other workspace files (for example `.env` or `.pem`) are not readable. Secrets placed in an allowed file type inside the workspace remain readable, so the workspace must not contain them. It has no shell, network, write, delete, or arbitrary-code tool. In the `agent` CLI, each tool call runs in a digest-pinned Docker container with no network, a read-only root filesystem and workspace mount, all capabilities dropped, `no-new-privileges`, a non-root user, and pids/memory/CPU limits; Docker failures fail closed. This container sandbox has been tested on one Windows host only and has not been independently reviewed.

A proposal is inert data. Applying it requires a valid HMAC-SHA256 signature over the exact approval payload, bound to the proposal digest, plus a current base-digest check. The signing key must be stored outside the repository. HMAC authenticates possession of a shared secret, not a human identity; anyone who obtains the key can sign approvals. OS-level account permissions or a separate signing service are still needed for stronger identity boundaries.

Implemented:
- Safe skill IDs and path containment checks, including symlink escape tests.
- Bounded tool loop (at most eight calls), calculator AST allowlist, read-only workspace tools, file size limits and path containment.
- Structural candidate checks and required deterministic regression-case checks before proposal creation.
- Exact proposal digest and base digest checks.
- Versioned HMAC-signed approval artifacts bind the exact proposal and a SHA-256 key identifier.
- Revoked key IDs are rejected for signing and application. Each revocation is recorded both in the verified audit ledger and in a per-user, owner-only revocation registry at a fixed profile location. The registry fails closed if it is missing, corrupt or over-permissive, so switching to another ledger file does not restore a revoked key.
- Applying a proposal requires the matching approval-signed record (proposal, key ID and signature digest) in the same audit ledger.
- Prior-version archive and transaction journals; interrupted transactions can be reconciled or rolled back.
- Hash-chained audit, cross-process writer lock, and fsync on append. On Windows the audit, governance and revocation-registry locks use LockFileEx, so a waiting writer is woken as soon as the holder releases. A lock not granted within the 10 s acquisition deadline fails closed with an error, and nothing is written. The deadline bounds the wait for the lock, not the total time to return: a pending request is cancelled and its completion awaited before its memory and handles are released, which can take longer if the driver or storage is slow. That cleanup tolerates repeated Ctrl+C, unlocks a lock that was granted during an interruption, and reports an unexpected unlock failure while still closing the handle.
- No-model inference is recorded as not executed, rather than passed off as a model answer; the model adapter raises instead of returning any text when no model is configured. Answers from `ask` and `agent` are labelled on stderr as model output that is not fact-checked, `ask` reports the model in `generated_by`, and its review verdict is `unverified_model_output`: only a non-empty check, not a quality check.
- Network access occurs only when an Ollama model is explicitly configured. The Ollama endpoint must be on this computer unless `OLLAMA_ALLOW_REMOTE=1` is set, and a remote endpoint must use https.

- An optional per-user approver list (`add-approver`) binds approval keys to names; once it exists, signing and applying require a listed pair. Without one, the single-operator default applies and is recorded in each signed event.
- `anchor-audit` records a ledger's last hash outside the ledger, so `verify-audit` notices a full rewrite or truncation. A process running as the same user can edit both, so a hash should also be kept off the machine.
- The real sandbox tests run in CI on Linux with skips forbidden.

**Model refusal is not a control.** The live D3.7 evaluation failed twice (latest: 16 of 90 attack runs attempted something forbidden, 66 of 90 refused properly). No secret leaked and no forbidden action ran in either run, because the capability boundary and sandbox blocked them. This is accepted for personal use as a known limitation.

Not implemented or not yet verified:
- Independent review of the container sandbox, Windows Docker coverage in CI, everyday use on Linux, any macOS use, and a safe way to add future privileged tools.
- A robust semantic answer-quality or prompt-injection evaluator. Candidate phrase screens and substring regression checks are narrow and can be gamed.
- Live-model behaviour on any model or host other than `qwen3:8b` on the owner's Windows PC.
- External immutable audit storage, enforced external identity/per-user roles, and protection against all concurrent revocation/apply races.
- Power-loss fault injection across every file-write window.
- Independent adversarial security review. The D7 holdout evaluation exists but had a single, non-independent rater.

Do not expose this development system to untrusted users or add privileged tools without additional controls. Passing CI does not establish production readiness.
