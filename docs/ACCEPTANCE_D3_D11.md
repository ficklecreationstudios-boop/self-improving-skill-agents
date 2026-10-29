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

## Clean-room verification record - 2026-10-27

### Result

**Outcome: PASS for the defined clean-room offline verification scope. This is not a release approval.**

A disposable copy of the project was created at:

`D:\self-improving-skill-agents-evidence\cleanroom-retry-20261027-185629`

The copy used the recorded source revision `8015607c0e0b5c20a5669e5c560555e1db2f6534`. The source worktree at the time of the recorded seal contained existing changes to `src/self_improving_agents/ollama.py`, `tests/test_ollama.py`, `tests/test_prompt_injection_live.py`, and untracked files `d3_experimental_think_false.patch`, `ollama.py.d3-think-false-backup`, and `tests/test_security_report.py`. These were preserved; this verification did not stage, commit, merge, or push them.

Environment and checks:

- Runtime: Python 3.15.2 (`C:\Python315\python.exe`).
- Test dependencies: installed from `requirements-test.lock`; installation exit code 0.
- Project package: editable installation succeeded; exit code 0.
- Import: succeeded from the disposable copy's `src/self_improving_agents/__init__.py`.
- CLI: `python -m self_improving_agents.cli --help` succeeded; exit code 0.
- Offline suite: **91 passed in 13.59 seconds; exit code 0**.
- The offline suite explicitly excluded `tests/test_prompt_injection_live.py` and `tests/test_ollama_live.py`. No live prompt-injection benchmark or completed think:false experiment was rerun.

Evidence and integrity:

- Project-file manifest: 115 files; verification reported zero missing or mismatched hashes.
- Evidence manifest: 15 entries; verification reported zero missing or mismatched hashes.
- Manifest sidecar: matched the recalculated SHA-256.
- Evidence manifest SHA-256: `6A1BBC954E3D9D3C1CD8EC154F359BA1E1906485A11CF8C1CE94F46C1C1FD314`.
- Offline suite log: `cleanroom-offline-suite.log`.
- Offline suite exit record: `cleanroom-offline-suite-exit.txt`.
- Project-file manifest: `cleanroom-project-file-manifest.csv`.
- Evidence hash manifest: `cleanroom-evidence-hashes.csv`.

This establishes successful installation, import, CLI help, offline tests, and internal hash consistency for this copy and Python version. It does not prove cross-version compatibility, a tamper-proof external timestamp, universal security, or release readiness. The initial failed clean-room attempts remain historical evidence and are not reclassified as passes.

### Acceptance-gate status and execution priority

This ordering is an execution priority, not a change to acceptance criteria. Existing thresholds, holdouts, required reviews, and release approval requirements remain unchanged. Completed experiments should not be repeated unless an identified gap requires a new, separately scoped and justified test.

1. **D3 - Security (PARTIAL):** Obtain independent adversarial review of the existing bounded five-case live-security evidence and its report audit. Agree on any additional testing only through the existing review process. Do not rerun the completed benchmark merely to refresh evidence.
2. **D8 - Least privilege (PARTIAL):** Implement and verify the required OS-level sandbox and its boundaries. Existing application-level restrictions alone do not close this gate.
3. **D4 - Governance (PARTIAL):** Complete independent review of identity/role enforcement and concurrency behavior. HMAC possession alone is not identity evidence.
4. **D5 - Audit durability (PARTIAL):** Conduct the required power-loss/filesystem-durability drills and backup restoration checks. Preserve existing audit evidence; add dated records for new drills.
5. **D7 - Quality and calibration (OPEN):** Establish the required labeled dataset, preregistered thresholds, scorer-correctness fixtures, calibration evidence, and independent adjudication before relying on quality claims.
6. **D6 - Self-improvement (PARTIAL):** Complete independent semantic evaluation and evaluation on an untouched external holdout under the existing preregistered gates. Do not reuse exposed data as an untouched holdout.
7. **D9 - Operations (OPEN):** Extend the new clean-room result into the existing operations acceptance process. The install/import/CLI/offline-suite result is supporting evidence, not a substitute for the full required clean-machine configuration, offline/no-model behavior, backup/recovery, upgrade, rollback, and uninstall run record.
8. **D10 - Human governance (PARTIAL):** Supply independent evidence for external identity, key lifecycle, and separation of duties.
9. **D11 - Release readiness (OPEN):** Reconcile all upstream gate evidence, complete independent review, and obtain owner approval for the exact immutable release commit. No release approval is implied by this record.

D0 reproducible build remains recorded as PASS; D1 lifecycle and D2 local model integration remain recorded as COMPLETE under their existing evidence. D12 and D13 are not defined in the current acceptance documents; no criteria or completion claims are invented for them.

### Decision

Close the **clean-room verification subtask** as passed for the stated scope. Keep the overall application **not release-approved** while D3-D11 retain the open or partial statuses above. Preserve all previous failed runs, experiment records, thresholds, and worktree changes.

## D8 OS sandbox status correction - 2026-10-29

**Correction to the earlier status:** Item 2 of the 2026-10-27 execution priority list above ("Implement and verify the required OS-level sandbox and its boundaries") is stale with respect to the container implementation and tests reported in the 2026-10-29 reconciliation. The 2026-10-27 record is left unchanged as history.

The 2026-10-29 local regression evidence includes a kernel-level isolation probe (`tests/test_container_os_sandbox.py`), real container integration (`test_real_docker_container_integration`) and a mount-escape test (`tests/test_container_workspace_integration.py`), run against Docker Engine 29.9.2 and the digest-pinned sandbox image. The probe asserts non-root execution (uid 65534), zero effective capabilities, `NoNewPrivs`, seccomp filter mode, pids/memory/CPU cgroup limits, a read-only root filesystem and read-only mounts, blocked outbound networking, and fork-bomb containment below 40 processes with child cleanup.

This correction records the newer evidence; it does not establish that every D8 acceptance criterion is satisfied. Testing covered one Windows host only; supported host platforms are not yet defined, and the sandbox escape review required by D8 has not taken place. Release acceptance remains pending review of the exact candidate commit, CI results tied to that commit, and the outstanding platform, security-review and acceptance requirements.

**Evidence boundary:** The trial-merge copy (`D:\d8_os_test_temp\candidate-reconciliation-20261029\trial-merge-run`) and the integrated worktree (`D:\d8_os_test_temp\a-integrate-b-20261029\full-regression`, log SHA-256 `37792AAC46B48BC291A67C024E10C6F3F7056E473947A5CB6EE4351CF3F71158`) each exited 0 with **154 passed, 11 skipped**. The 11 skips are 5 symlink tests (symlink privilege unavailable to the runner; these 5 passed separately in an elevated owner shell, `D:\d8_os_test_temp\symlink-tests-userShell-20261029-050812`) and 6 opt-in live-model tests (run separately with `OLLAMA_THINK=false`, `D:\d8_os_test_temp\live-security-think-false-full-20261029`). Both separate runs used the worktree **before** the 2026-10-29 integration of the model-sentinel and report-allowlist fixes; they must be rerun against the candidate commit. These results support the tested uncommitted copies only and are not a substitute for CI evidence against the eventual candidate commit.
