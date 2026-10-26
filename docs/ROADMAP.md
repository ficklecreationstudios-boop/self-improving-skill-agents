# Roadmap and acceptance gates

## P0 — Foundation
Typed task and skill records, CLI, local audit ledger, package structure, baseline tests. The earlier foundation suite passed CI.

## P1 — Routing and retrieval
Discover Markdown skill metadata; select by domain/tags; load only selected skill bodies; enforce paths within the skill root. Skill content is untrusted context; symlink containment is tested.

## P2 — Execution and QA
Explicit Ollama adapter and failure handling; record input/output provenance; basic non-empty output review. If no model is configured, task execution fails closed and is audited as not executed. No tool execution exists.

## P3 — Feedback-driven candidate proposals
Record user feedback, ask a configured local model to draft a complete skill candidate, apply structural and narrow risky-phrase checks, run a required JSONL behavioral regression suite, and create a digest-bound proposal only when the checks pass. The active skill is never mutated by this flow. These substring checks are not semantic quality or safety proof.

## P4 — Signed governance
A separate approval command produces an HMAC-SHA256 signature bound to the exact proposal digest. Applying verifies the signature, rechecks the current skill base digest, archives prior content, and writes an audit event. The key authenticates possession of a shared secret, not the approver's real-world identity.

## P5 — Measurement and audit durability
Routing smoke evaluation, concurrent audit-writer locking, hash-chain verification, and fsync on appended events. The context-size proxy counts whitespace-separated pieces, not model tokens.

## Remaining before production
Live Ollama testing on the owner's Windows environment; independent held-out routing/quality/safety corpus with preregistered thresholds; robust semantic and prompt-injection evaluation; OS-level isolation if tools are introduced; key rotation/revocation and stronger identity/role controls; crash/power-loss fault injection; clean-machine recovery walkthrough; independent security review.
