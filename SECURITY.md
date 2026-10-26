# Security model

Task text, feedback, skill files, repository documents, workspace files, and tool results are untrusted input. The optional agent loop exposes only three allowlisted capabilities: bounded arithmetic, UTF-8 file reads inside a configured workspace, and text search inside that workspace. It has no shell, network, write, delete, or arbitrary-code tool. This is application-level least privilege, not an OS sandbox against a hostile local process or a compromised interpreter.

A proposal is inert data. Applying it requires a valid HMAC-SHA256 signature over the exact approval payload, bound to the proposal digest, plus a current base-digest check. The signing key must be stored outside the repository. HMAC authenticates possession of a shared secret, not a human identity; anyone who obtains the key can sign approvals. OS-level account permissions or a separate signing service are still needed for stronger identity boundaries.

Implemented:
- Safe skill IDs and path containment checks, including symlink escape tests.
- Bounded tool loop (at most eight calls), calculator AST allowlist, read-only workspace tools, file size limits and path containment.
- Structural candidate checks and required deterministic regression-case checks before proposal creation.
- Exact proposal digest and base digest checks.
- HMAC-signed approval artifact workflow; short/wrong keys and altered signatures fail closed.
- Prior-version archive and transaction journals; interrupted transactions can be reconciled or rolled back.
- Hash-chained audit, cross-process writer lock, and fsync on append.
- No-model inference is recorded as not executed, rather than passed off as a model answer.
- Network access occurs only when an Ollama model is explicitly configured.

Not implemented or not yet verified:
- OS-level sandboxing, process isolation, and a safe way to add future privileged tools.
- A robust semantic answer-quality or prompt-injection evaluator. Candidate phrase screens and substring regression checks are narrow and can be gamed.
- Live Ollama integration on the owner's Windows machine.
- External immutable audit storage, key rotation/revocation, per-user identities or role management.
- Power-loss fault injection across every file-write window.
- Independent adversarial security review and a held-out quality benchmark with preregistered thresholds.

Do not expose this development system to untrusted users or add privileged tools without additional controls. Passing CI does not establish production readiness.
