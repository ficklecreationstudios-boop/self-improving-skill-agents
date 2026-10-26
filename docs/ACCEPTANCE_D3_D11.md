# D3–D11 fixed acceptance plan and evidence boundaries

This document fixes the evidence needed to close each remaining gate. A gate may be marked PASS only when every required row is supported by linked, reproducible evidence. A test suite passing is not itself a safety or release claim.

## D3 — Skill and tool security

**Acceptance:** (1) parser rejects malformed metadata, duplicate IDs, path traversal, symlink escapes and oversized inputs; (2) capability registry rejects unknown tools, malformed arguments, traversal and bounded-resource violations; (3) a versioned adversarial corpus includes direct prompt injection, tool escalation, data exfiltration, indirect injection through skills/files/tool output and refusal/abstention cases; (4) live results are run against the exact model tag and recorded with model digest/version, prompt/corpus hashes and per-case output digests; (5) an independent reviewer reviews failures and bypass attempts. CI-only fake-adapter tests do not close the live-model portion.

**Current limitation:** live-model security tests require the owner's local Ollama service. Run with `RUN_SECURITY_INTEGRATION=1`, the exact `OLLAMA_MODEL` tag, and `SECURITY_BENCHMARK_REPORT` set to an absolute JSONL path outside the repository. The report records the model digest, input/output hashes, tool names, attack outcome flags and UTC timestamp without storing raw output. A finite benchmark can establish bounded evidence for that model/corpus, never universal resistance.

## D4 — Governance

**Acceptance:** exact proposal digest and current base digest bound to approval; rejected/unapproved, stale, malformed, replayed and tampered approvals fail closed; key identifiers and revocation state are checked at signing and application; role/approver authorization policy is explicit; every approval/rejection/revocation is auditable; recovery is deterministic after each transaction boundary. A shared HMAC secret proves possession only, not personal identity. Strong identity requires an external identity provider or signing service and a separate security review.

## D5 — Audit durability

**Acceptance:** hash-chain verification detects tampering, malformed records, sequence gaps and altered payloads; append refuses corrupt ledgers; multi-process writers serialize without lost/duplicated events; every transaction fault-injection point recovers to a documented committed or rolled-back state; file and directory durability semantics are tested on supported filesystems; clean restart and backup restoration preserve verification. Simulated exceptions do not substitute for power-loss testing.

## D6 — Self-improvement

**Acceptance:** feedback and candidate-generation failures are audited; candidate changes remain inert until approval; frozen regression corpus and thresholds are hashed before candidate evaluation; candidate and active skill digests are recorded; any regression failure, evaluator error, model timeout, stale base or invalid audit prevents proposal/application; independent held-out evaluation is untouched by candidate tuning. Substring assertions alone do not close semantic quality.

## D7 — Quality, calibration and safety evaluation

**Acceptance:** versioned, labeled datasets have separate development, calibration and untouched holdout splits; case IDs are unique; task success, routing, abstention, unsafe-action rate, unsupported claims and domain slices are measured with confidence intervals; thresholds are registered before inference; scorer correctness is tested against hand-calculated fixtures; independent human review adjudicates ambiguous semantic outputs; results include all failures and abstentions. Model-generated confidence is not considered calibrated without empirical calibration analysis. The current phrase scorer is diagnostic only.

## D8 — Least privilege and isolation

**Acceptance:** application capability allowlist, strict argument schemas, path containment, byte/count/time/step bounds and deny-by-default tests pass; hostile symlink and traversal cases are covered; a separate OS sandbox test demonstrates filesystem, process, and network restrictions for the supported host platforms; sandbox escape attempts are reviewed. Current in-process restrictions are not an OS sandbox.

## D9 — Operations

**Acceptance:** clean-machine install, first-run configuration, offline/no-model behavior, backup, restore, audit verification, interrupted-update recovery, upgrade, rollback, logging/diagnostics and uninstall are exercised from a versioned runbook on supported platforms. Record OS/Python/package versions and command outputs. A document alone is not execution evidence.

## D10 — Human governance

**Acceptance:** approver roles and authorization are enforced outside untrusted model content; approval keys are generated securely, kept out of the repo, access-controlled, rotated and revocable; revoked keys fail closed; approvals bind exact proposals; audit events record decision provenance without exposing secrets; two-person review is exercised for high-risk updates. A label supplied on a CLI command is not verified identity.

## D11 — Release readiness

**Acceptance:** D0–D10 each pass their own gates; release artifact is reproducible and has an SBOM/dependency review, threat model, documented known limitations, rollback plan, incident response steps, clean-machine acceptance record and independent security review. The owner explicitly signs off on a specific immutable release commit. Until then, no production-ready claim is permitted.

## Current evidence and blockers

- GitHub CI can test deterministic code paths, concurrency probes, documentation and fake-adapter behavior.
- Real Ollama prompt-injection evaluation, host OS sandbox verification, clean-machine installation/recovery, filesystem/power-loss testing, key access-control verification and independent security review require execution outside GitHub Actions and/or an independent reviewer.
- No gate is considered complete solely because a file says COMPLETE. The evidence and exact commit must be linked.
