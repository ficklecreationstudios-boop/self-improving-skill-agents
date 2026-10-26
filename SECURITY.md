# Security model

Task text, feedback, skill files, proposal files, and repository documents are untrusted input. Agents receive no tools in this implementation. Ollama generates text only and cannot invoke host tools through this code.

A proposal is inert data. Applying it requires a valid HMAC-SHA256 signature over the exact approval payload, bound to the proposal digest, plus a current base-digest check. The signing key must be stored outside the repository. HMAC authenticates possession of a shared secret, not a human identity; anyone who obtains the key can sign approvals. OS-level account permissions or a separate signing service are still needed for stronger identity boundaries.

Implemented:
- Safe skill IDs and path containment checks, including symlink escape tests.
- Structural candidate checks and required deterministic regression-case checks before proposal creation.
- Exact proposal digest and base digest checks.
- HMAC-signed approval artifact workflow; short/wrong keys and altered signatures fail closed.
- Prior-version archive, hash-chained audit, cross-process writer lock, and fsync on append.
- No-model inference is recorded as not executed, rather than passed off as a model answer.
- Network access occurs only when an Ollama model is explicitly configured.

Not implemented or not yet verified:
- OS-level sandboxing and process isolation.
- A robust semantic answer-quality or prompt-injection evaluator. The candidate phrase screen and substring regression checks are narrow checks and can be gamed.
- Live Ollama integration on the owner's Windows machine.
- External immutable audit storage, key rotation/revocation, per-user identities or role management.
- Crash/power-loss fault injection across all file-write windows.
- Independent adversarial security review and held-out quality benchmark.

Do not expose this development system to untrusted users or provide privileged tools without additional controls. Passing CI does not establish production readiness.
