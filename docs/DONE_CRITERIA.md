# Definition of Done: Autonomous Skill-Agent System

This document fixes the completion gates. A green unit-test run alone does not satisfy them. Status must be marked **PASS** only when the named evidence is recorded; otherwise use **OPEN** or **BLOCKED**.

## Required gates

| Gate | Pass condition | Evidence required | Initial status |
|---|---|---|---|
| D0 Reproducible build | Clean install and all tests pass on supported Python versions and Windows/Linux | CI run URLs, dependency lock or pinned build inputs | OPEN |
| D1 Task lifecycle | Request → route → retrieve skills → generate → validate → deliver → audit is exercised end-to-end | deterministic integration tests and recorded outputs | OPEN |
| D2 Local-model integration | Real configured Ollama endpoint/model works; timeout, unreachable server, malformed response and model mismatch fail clearly | integration run metadata; no invented model results | OPEN |
| D3 Skill security | Traversal, symlink escape, duplicate IDs, malformed metadata, oversized input and prompt-injection fixtures are tested | adversarial regression suite | IN PROGRESS |
| D4 Governance | Proposals are inert; approvals bind exact content and base; stale, duplicate, unapproved and invalid-audit updates fail closed; recovery is tested | governance tests and immutable evidence | IN PROGRESS |
| D5 Audit durability | Tampering is detected; append refuses corrupted history; crash/restart behavior and concurrent writers are tested | fault-injection and concurrency tests | IN PROGRESS |
| D6 Self-improvement loop | Failures generate candidate improvements; candidates run against fixed holdouts; regression and safety gates block regressions; approved changes can be rolled back | benchmark dataset, preregistration, repeated results | OPEN |
| D7 Quality and calibration | Routing, task success, abstention, unsafe actions and hallucinated claims measured on held-out examples; acceptance thresholds set before evaluation | versioned dataset, scorer, run reports | OPEN |
| D8 Least privilege | No arbitrary shell/tool execution by default; capabilities are allowlisted, arguments validated, time/resource bounded, and sandboxed | threat model and sandbox tests | OPEN |
| D9 Operations | Install/uninstall, config, logs, backup/recovery, offline operation, upgrades and rollback documented and exercised | clean-machine walkthrough | OPEN |
| D10 Human governance | Approval identity is authenticated when required; roles, revocation, key storage and recovery are tested | security review and tests | OPEN |
| D11 Release readiness | All gates above pass, known limitations documented, independent review complete, owner approves release | release checklist and explicit owner sign-off | OPEN |

## Rules

- No completion percentage is assigned without an evidence-backed denominator.
- Passing CI means the checked tests passed, not that all gates passed.
- The default branch and production use remain unchanged until separately authorized.
- Do not claim universal correctness or 100% safety. The goal is a bounded, testable system with explicit failure behavior and evidence.
- Self-improvement must never bypass review, held-out evaluation, safety gates, or rollback.
