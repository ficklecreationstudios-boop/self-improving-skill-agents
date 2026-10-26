# Definition of Done: Autonomous Skill-Agent System

This is the fixed completion checklist. A green unit-test run alone does not satisfy it. A gate is **PASS** only when the required evidence is linked; otherwise it remains **OPEN** or **PARTIAL**.

| Gate | Pass condition | Evidence required | Status |
|---|---|---|---|
| D0 Reproducible build | Pinned clean install and all tests pass on supported Python versions and Windows/Linux | [CI run 40347774146](https://github.com/ficklecreationstudios-boop/self-improving-skill-agents/actions/runs/40347774146), code commit f9059457af966ca0673661f1d6c7784d8a411eb9 | **PASS for that code commit** |
| D1 Task lifecycle | Request → route → generate → validate → deliver → audit, including failure/stopped states, tested end-to-end | Integration tests and recorded outputs | PARTIAL |
| D2 Local-model integration | Real configured Ollama endpoint/model works; timeout, unreachable server, malformed response and model mismatch fail clearly | Live local integration run metadata | OPEN |
| D3 Skill and tool security | Traversal, symlink escape, duplicate IDs, malformed metadata, oversized input and prompt-injection fixtures tested | [D3 security PR](https://github.com/ficklecreationstudios-boop/self-improving-skill-agents/pull/2), [CI run 40377347096](https://github.com/ficklecreationstudios-boop/self-improving-skill-agents/actions/runs/40377347096), commit e892608b5117d197bbec50fdffefe3e655460578 | PARTIAL; adversarial fixtures pass, but prompt-injection resistance is not established |
| D4 Governance | Inert proposals; signed approval binds exact proposal; stale/duplicate/unapproved/invalid-audit updates fail closed; interrupted transaction recovery tested | Governance tests and recovery evidence | PARTIAL |
| D5 Audit durability | Tampering detected; invalid append blocked; concurrent writers serialized; crash recovery tested | Concurrency tests plus power-loss fault-injection results | PARTIAL |
| D6 Self-improvement loop | Feedback produces candidate; structural and frozen regression checks gate proposal; failures audited; active skill unchanged | Lifecycle tests and independent evaluation | PARTIAL; behavioral checks are substring-based |
| D7 Quality and calibration | Routing, task success, abstention, unsafe actions and hallucinated claims measured on held-out examples; thresholds preregistered | Versioned holdout, scorer, report | OPEN |
| D8 Least privilege | Allowlisted capabilities, validated arguments, bounded inputs/steps, no shell/network/write by default; OS sandbox tested | Threat model and sandbox tests | PARTIAL; application-level bounds only |
| D9 Operations | Install/uninstall, config, logs, backup/recovery, offline operation, upgrades and rollback exercised | Clean-machine walkthrough | OPEN |
| D10 Human governance | Approval key lifecycle, revocation and stronger identity/roles verified | Security review and key-management tests | PARTIAL; HMAC proves shared-key possession only |
| D11 Release readiness | All gates pass, limitations documented, independent review complete, owner explicitly approves release | Release checklist and owner sign-off | OPEN |

## Non-negotiable rules

- No completion percentage without an evidence-backed denominator.
- CI proves only the tests it ran passed; it does not prove general correctness or safety.
- Default branch and production remain unchanged until separately authorized.
- Do not claim universal correctness or 100% safety.
- Self-improvement must never bypass evaluation, signed review, safety gates, or rollback.
