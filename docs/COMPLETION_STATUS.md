# Completion status (2026-11-02)

New to the project? Read [HANDOFF.md](HANDOFF.md) first.

**Scope: one owner, one Windows 11 host, local use.** This is a status record, not a release approval. No merge, deployment or production adoption follows from it. `DONE_CRITERIA.md` and `RELEASE_CHECKLIST.md` remain the release standard, and that standard is **NOT APPROVED**.

All validation was done by the implementer (Claude). None of it is independent. Evidence is outside the repository, under `D:\d8_os_test_temp`.

## Bottom line

- **Implementation:** everything engineering could do on the remaining list is done.
- **Not passed:** D3.7 live-model refusal **failed again**. It cannot be closed by more engineering on this model without tuning against its corpus. The owner accepted this for personal use as a known limitation, not a pass, and kept the stronger prompt provisionally, with no further tuning against those cases.
- **Not closable here:** two-person review, verified identity and a real power-loss test need other people or other equipment. The owner recorded independent review as not applicable to personal use; it stays required for any wider release.
- **Adopted:** the owner authorized adopting `97794bbe83c82ca5f82de5810edfbe23914e0439` on the work branch for personal use. Nothing was merged to `main`, and nothing was deployed. Documentation commits may follow that commit.
- **Owner's call:** any release decision.

## Candidate and results

| Check | Result |
|---|---|
| Code commit | `71c4312cdac8eafc915a2a8527341567cf5e7bfe` (documentation commits follow it) |
| Hosted CI, run 41472404962 | 6 of 6 jobs passed: Windows and Ubuntu on Python 3.11 and 3.14, `docker-sandbox`, `clean-windows-ops-drill` |
| Local, Windows, Python 3.14, real Docker and live model | 544 passed, 0 failed, 8 skipped; every skip is a symlink test needing a privilege this shell lacks. `final-acceptance-20261102\final-windows-314-docker-live.txt` |
| Local, Windows, Python 3.11, real Docker | 538 passed, 0 failed, 14 skipped |
| Elevated local run | Not repeated on this commit. Hosted Windows jobs run elevated. The last owner-run elevated pass was before this work, in `ci-41389807313\fix` |

## Gates, for personal use

| Gate | Status | Evidence | Not covered |
|---|---|---|---|
| D0 build | PASS | CI above | Pass and skip counts per hosted job were not read; the logs need admin sign-in |
| D1 lifecycle | PASS | Suite and CI | — |
| D2 local model | PASS | Live tests above | One model, one host |
| D3 security | **Enforcement PASS; model refusal FAIL** | `d37-rerun-20261102\D37-RESULT.md`: T1 0 leaks, T2 0 executed, T3 16/90 against a limit of 4, T4 66/90 against a minimum of 72 | The model still attempts and echoes prohibited things. Run 2's corpus was not untouched |
| D4 governance | PASS, single operator | Approver policy (D4.3) tested and exercised in the drill | HMAC proves possession, not identity |
| D5 audit | PASS, residual risk accepted | Earlier crash drill; anchors (F7) added | Real power loss not tested, accepted by the owner |
| D6 self-improvement | PASS, unchanged | `d7-quality-eval-20261030\d6` | Evidence predates this work, single rater |
| D7 quality | PASS, unchanged | `d7-quality-eval-20261030\D7-RESULT.md`. It uses the `ask` path, which the agent prompt change does not touch | Small n, single rater |
| D8 least privilege | PASS for this host | Real-Docker tests locally on Windows and in CI on Linux, skips forbidden | Docker Desktop and kernel escape; Windows Docker is not in CI, because hosted runners have no Linux containers |
| D9 operations | PASS for what it ran | `scripts/ops-drill.ps1` on a clean hosted Windows runner: install, first run, no-model, approver policy, key rotation, anchors, backup and restore, recovery, rollback and upgrade, uninstall | Windows Server rather than Windows 11; no live-model or container steps, which ran locally instead |
| D10 human governance | PASS, single operator | Key ACL, rotation and revocation in the drill and tests | Two-person review and verified identity do not apply to one person. This is a disposition, not evidence |
| D11 release | **NOT APPROVED** | This record | Independent review, owner sign-off on an immutable commit |

## Items from the remaining-work list

- **Docker CI: done.** `docker-sandbox` pulls the pinned image and fails if any real-sandbox test would skip. Sandbox tests now also run on Linux; application use remains Windows only.
- **F7, ledger anchor: done.** `skill-agents anchor-audit` records the last event outside the ledger, and `verify-audit` then notices a full rewrite or truncation. A process running as this user could edit both files, so keep the printed hash off the machine too. Anchors are not automatic: one must be taken.
- **D4.3 and D10, approver policy: done.** `skill-agents add-approver` binds a key to a name. Without a list, the single-operator default applies and is recorded in each signed event. The owner's real approver list and first ledger anchor were created at adoption. Their values are not recorded in this public repository.
- **F6 / Fix 4B, faster ledger writes: decided not to do.** One write takes 48 ms at 3,000 entries, and a typical agent run adds 2 to 6 entries, so the cost does not justify the change in code that protects the ledger. Revisit if a ledger nears tens of thousands of entries.
- **F9 tidy-up:** the dead expression in `agent_loop.py` is removed.
- **SYSTEM entry origin: unexplained.** The fix replaces the whole access list, so it does not depend on the origin.

## Behaviour change to know about

The agent prompt now tells the model to decline out-of-scope requests. Attempts fell from 56/90 to 16/90 and benign tasks still work, but in the same run every ambiguous-case answer was a refusal, and two injected-content tasks refuse without doing the safe part. **The agent is safer in tests and less helpful on borderline requests.** The prompt is not a security control.

## After adoption

Run from the live folder at `97794bb`, not elevated, with Docker required: Windows on Python 3.14 and 3.11 each gave 538 passed, 0 failed, 14 skipped (8 symlink tests lacking the privilege, 6 live-model tests not enabled). A normal `skill-agents agent` run then read a file through the sandbox correctly, using a throwaway folder and ledger.

**Not yet exercised:** a real sign-and-apply on real skills. It has only been drilled on disposable data.

## Environment problems found since

- **Docker Desktop lost its mount of `D:` twice** (2026-11-02 and by 2026-11-05), reporting "no such device", and container tools failed safely. A restart fixed the first. A remount without a restart fixed the second, and 61 real-Docker tests then passed from `D:`, with 3 symlink skips. See [HANDOFF.md](HANDOFF.md#if-docker-loses-a-drive).
- **Hosted CI run 42031819353 failed `docker-sandbox`** on a documentation-only commit: 59 passed, 1 failed, with `docker info` not answering within 5 s, according to the job log as reported by the owner's review. The other 5 jobs passed, and this job had passed 6 times before. `docker pull` had just succeeded in the step before, so it does not look like a startup problem. The cause is not proven. Docker checks in tests now share a 30 s limit and report the real error, and a check that still doesn't answer fails rather than skips. One green run cannot prove this fixed a failure this rare.

## First-use walkthrough

Done on 2026-11-05 with a throwaway folder and ledger, following [HANDOFF.md](HANDOFF.md#first-use-walkthrough). The answer was correct, there was one `read_text_file` call, the ledger verified, and no containers were left behind. The real ledger and key were not touched. The walkthrough did add an anchor for the throwaway ledger to the shared per-user anchors file, which is harmless but was a mistake. The owner's real anchor still verifies.
