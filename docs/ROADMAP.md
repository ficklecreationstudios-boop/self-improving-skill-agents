# Roadmap and acceptance gates

## P0 — Foundation
Typed task and skill records, CLI, local audit ledger, package structure, baseline tests. Gate: imports and tests pass from a clean checkout.

## P1 — Routing and retrieval
Discover Markdown skill metadata; select by domain/tags; load only selected skill bodies; enforce paths within the skill root. Skill content is untrusted context.

## P2 — Execution and QA
Explicit Ollama adapter; deterministic no-model fallback; record input/output provenance; basic review record. No tool execution.

## P3 — Learning proposals
Create proposals with base digest, proposed content, rationale, and proposal digest. Proposals never mutate skills directly.

## P4 — Governance
Require explicit human approver and exact proposal digest; recheck base digest; archive prior content; write audit event. Reject stale, mismatched, or path-escaping proposals.

## P5 — Measurement
Regression suite and context-size proxy. Proxy counts whitespace-separated pieces, not model tokens. No token savings or quality superiority claims without tokenizer-backed and held-out evaluation.

## Remaining before production
Held-out routing/quality corpus and preregistered thresholds; cryptographic operator identity and signed approvals; process/OS isolation; external append-only audit; Windows CI; live Ollama testing; adversarial prompt-injection and path traversal testing.