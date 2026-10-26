# Roadmap and acceptance gates

## P0 — Foundation
Typed task and skill records, CLI, local audit ledger, package structure, baseline tests. Foundation tests pass in the recorded CI runs.

## P1 — Routing and retrieval
Discover Markdown skill metadata; select by domain/tags; load only selected skill bodies; enforce paths within the skill root. Skill content is untrusted context; symlink containment is tested.

## P2 — Execution and QA
Explicit Ollama adapter with bounded prompt/output sizes and failure handling; record input/output provenance; basic non-empty output review. If no model is configured, task execution fails closed and is audited as not executed.

## P3 — Feedback-driven candidate proposals
Record user feedback, ask a configured local model to draft a complete skill candidate, apply structural and narrow risky-phrase checks, run a required JSONL behavioral regression suite, and create a digest-bound proposal only when the checks pass. The active skill is never mutated by this flow. Substring checks are not semantic quality or safety proof.

## P4 — Signed governance and recovery
A separate approval command produces an HMAC-SHA256 signature bound to the exact proposal digest. Applying verifies the signature, rechecks the current skill base digest, archives prior content, journals transaction state, and writes an audit event. Recovery can finalize an audited update or roll back an update lacking a matching audit event. HMAC proves possession of a shared secret, not the approver's real-world identity.

## P5 — Measurement and bounded capabilities
Routing smoke evaluation, concurrent audit-writer locking, hash-chain verification, fsync on appended events, and a bounded tool loop with calculator/read-only workspace search. The context-size proxy counts whitespace-separated pieces, not model tokens. The agent loop has no shell, network, or write capabilities and is not OS-sandboxed.

## Remaining before production
Live Ollama testing on the owner's Windows environment; independent held-out routing/quality/safety corpus with preregistered thresholds; robust semantic and prompt-injection evaluation; OS-level isolation; key rotation/revocation and stronger identity/role controls; power-loss fault injection; clean-machine recovery walkthrough; independent security review.
