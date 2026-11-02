# Personal-use acceptance record (2026-10-30)

> Historical record at `e6c60e9`. For the current state, see [COMPLETION_STATUS.md](COMPLETION_STATUS.md). Later work fixed several limits named here, and the owner later ended the external review process for personal use.

**Scope: one owner, one Windows 11 host, local use only.** This record does **not** approve release, distribution, enterprise or production use by others, and it does not replace `DONE_CRITERIA.md` or `RELEASE_CHECKLIST.md`. Those stay **NOT APPROVED** for anything beyond personal use.

- **Authority:** the owner's instruction of 2026-10-30 to finish all phases for single-user use, with no reviewers besides the implementer.
- **Validation:** every check below was run and verified by the implementer (Claude). **None of it is independent review.** Where a gate's criteria call for independence, this record says so instead of claiming it.
- **Evidence:** everything lives outside the repository under `D:\d8_os_test_temp`. Hashes are SHA-256.

## Candidate

| Item | Value |
|---|---|
| Code commit | `e6c60e9e3b57258582e378443abdcb37b5614779` (branch `work/d8-os-sandbox-20261027`, local, not pushed) |
| Supported platform | Windows 11 x64; Docker Desktop (Linux containers) Engine 29.9.2; Python 3.14 (3.11 also run) |
| Model | Ollama 0.40.11, `qwen3:8b` digest `500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41`, `OLLAMA_THINK=false` |
| Sandbox image | `python@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce` (never pulled automatically) |
| Runtime dependencies | none: standard library only |
| Test/build dependencies | `requirements-test.lock`: setuptools 80.9.0, pytest 9.1.1, iniconfig 2.3.1, packaging 26.3, pluggy 1.7.0, Pygments 2.21.0 |

## Test result at `e6c60e9`

- **Full suite with Docker and live models:** `full-suite-20261030-r2\full.log`, worktree diff `b453768e2677144a1886ebfc28c9c183b31059ec9a5f3559bfd59600f8c4c11a`.
  - Docker sandbox tests and the 6 live-model tests (`RUN_OLLAMA_INTEGRATION=1`, `RUN_SECURITY_INTEGRATION=1`, `OLLAMA_TIMEOUT=300`) were included.
  - **364 passed, 0 failed, 8 skipped.**
  - All 8 skips are symlink tests: this account lacks the Windows symlink privilege, and Developer Mode is off. Turning Developer Mode on lets them run. They are not skipped by choice.
- **Python 3.11.9 run (fresh venv from the lock file; Docker on, live models off):** **358 passed, 0 failed, 14 skipped**. The skips are the 8 symlink tests plus the 6 live-model tests, which were not enabled for this run. Log: `py311-suite-20261030\full.log`, `4afbbb90b2ad33ab8b0fcb6e45b816c546296f1590d0085eb8d50c1393fad416`.
- The full-suite log hash is recorded beside this file in the evidence folder.

## Gate status for personal use

| Gate | Personal-use status | Evidence | What is not covered |
|---|---|---|---|
| D0 build | PASS (local) | Python 3.14 suite above; Python 3.11 suite; last hosted CI was at `d2955438` (run 40925381804) | The three local commits after `d295543` have no hosted CI because they are not pushed. |
| D1 lifecycle | PASS | Existing CI evidence, plus a live `ask` and container `agent` run in the D9 drill | — |
| D2 local model | PASS | Live tests in the full suite; D3.7, D7 and D9 runs against the pinned digest | One model and one host |
| D3 security | **Enforcement PASS; model refusal FAIL** | D3.7: `d37-live-run-20261030\D37-RESULT.md`, 240 live runs. T1 leaks 0, T2 executed 0, T5 and T6 pass; **T3 attempts 56/90 and T4 refusals 15/90 fail** | The model calls advertised prohibited tools and follows injected instructions; the capability boundary blocked every attempt. Single rater; not independent. |
| D4 governance | PASS for single-user | Signed and digest-bound approvals; stale, replay, wrong-key and revoked-key rejection; D9 drill; key file ACL now owner-only on Windows (`84a3099`) | HMAC proves possession of a key, not identity. Roles and two-person review do not apply to one user. |
| D5 audit durability | PASS, with **residual risk accepted** | Hash chain, multi-process serialization, fault injection, 120-kill crash drill (0 violations), torn-tail recovery (`8cc0a00`), backup and restore in the D9 drill | **Real power-loss testing was not done.** The owner accepted this as a residual risk on 2026-10-30. |
| D6 self-improvement | PASS | `d7-quality-eval-20261030\d6\d6.log` `4b8721f1e3001d77c68344da509c756cabe52c2dd4d4cda594b8c9a86bf6c615`: live candidate, frozen 5-case holdout passed, active skill unchanged until signed apply, archive byte-identical, governed rollback restored the digest, audit valid | The candidate over-fitted the general skill to one task; human approval is the only semantic gate. Not independent. |
| D7 quality | PASS (holdout) | `d7-quality-eval-20261030\D7-RESULT.md`: preregistered, untouched 20-case holdout; Q1–Q8 all pass | n is small; single rater, not independent; one fabricated answer (Q7 at its limit); the phrase abstention detector is unreliable and stays diagnostic only. |
| D8 least privilege | PASS for this host | Real-Docker sandbox tests in the suite (non-root, no capabilities, no network, read-only, limits, mount-escape); implementer's review of the `docker run` flags | Docker Desktop and the WSL2 kernel are trusted. The whole workspace is mounted, with file-type filtering done by the worker. Symlink tests need Developer Mode. Linux hosts are unsupported. |
| D9 operations | PASS | Drill run 2: `d9-ops-drill-20261030-r2\drill.log` `875e20a1add3aa882a655669a8d5d3d0eeade47fe3ead351ca76ecdaf6b7b618`. Covers clean venv install, CLI, no-model, live ask and agent, governance, backup and restore, idempotent recovery, rollback and upgrade, uninstall. Run 1 (`d9-ops-drill-20261030`) **failed** and found the defect fixed in `e6c60e9`; it is preserved. | Same host, not a fresh machine |
| D10 human governance | PASS for single-user | Key ACL, revocation audited and enforced at sign and apply | No external identity provider; no separation of duties (one person) |
| D11 release | **Personal use only** | This record | No independent security review; distribution is not approved |

## Defects found and fixed during this work

1. **Approval keys were readable by other local users on Windows.** `init-approval-key` set `chmod 600` on POSIX only. Fixed in `84a3099`: the key file is restricted to the owner's SID before any key bytes are written, and key creation fails closed. Verified on the D9 key, whose ACL is `DESKTOP-L8N406O\Jarret:(F)` only.
2. **The fixed 60-second model timeout was too short** on this host, causing a D7 dev case to time out. Fixed in `84a3099`: `OLLAMA_TIMEOUT` is configurable, with a default of 60.
3. **An approved skill update could silently remove the skill.** Content that does not parse, such as a UTF-8 BOM from Windows PowerShell 5.1, was applied, and discovery then dropped the skill. Fixed in `e6c60e9`:
   - discovery ignores a leading BOM;
   - `apply`, `propose` and the learning screen refuse content that would not load with the same skill ID.

## Threat model (summary)

- **Assets:** the files in the workspace you point the agent at, skill content, the audit ledger and the approval key.
- **Untrusted inputs:** the model, task text, skills, workspace files and tool results.
- **Controls:**
  - capabilities are deny-by-default, limited to the calculator, read-only file reading and search;
  - tool calls run in the container sandbox;
  - skill changes need a signed approval bound to the exact proposal;
  - the audit ledger is hash-chained.
- **Key result:** D3.7 shows that **the model itself is not a security control**. It attempts prohibited actions and follows injected instructions, so safety depends on the capability boundary and the sandbox.
- **Operating rules:**
  - Never point `--workspace` at a folder containing secrets in readable file types (`.md`, `.txt`, `.py`, `.json`, `.yaml`, `.yml`, `.toml`).
  - Never add write, shell or network capabilities.
  - Read every skill proposal before approving it.

## Residual risks (accepted for personal use)

- Model refusal is unreliable (D3.7 FAIL). The model also fabricates answers about unknown facts (D7, `d7-hold-u3`).
- Real power loss is untested (D5).
- Docker Desktop, WSL2 and kernel escapes are out of scope.
- HMAC approvals prove possession of the key, not identity.
- All validation was done by the implementer. No independent review exists.

## Rollback and incident response

- **Code rollback:** check out a previous commit (for example `ca6e67a`) and reinstall it with `pip install --no-build-isolation -e .`. The D9 drill showed that both versions verify the same audit ledger.
- **Skill rollback:** propose the archived content from the archive folder as a new signed proposal (exercised in D6).
- **Possible key compromise:**
  1. run `skill-agents revoke-approval-key <key-id>`;
  2. create a new key;
  3. run `skill-agents verify-audit`.
- **After a crash:**
  1. run `skill-agents recover-audit`, then `skill-agents recover`;
  2. restore from backup if verification fails.
- **Backups:** stop all writers, then copy the skills folder, `data/` (audit ledger and archive) and the key, which goes outside the repository. Verify the copy with `verify-audit`.
