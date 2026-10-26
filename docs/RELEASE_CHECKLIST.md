# Release readiness checklist — not approved

This is a release evidence template, not an authorization. Keep status **NOT APPROVED** until all fields are completed and the owner signs the exact immutable commit.

## Candidate identity
- Candidate commit SHA:
- Source branch:
- Release artifact SHA-256:
- Build environment and dependency-lock SHA-256:
- Supported OS/Python matrix:

## Gate evidence
- [ ] D0 reproducible clean build and full CI
- [ ] D1 task lifecycle evidence
- [ ] D2 local model endpoint evidence for exact model digest
- [ ] D3 security corpus, local model-specific results, independent adversarial review
- [ ] D4 governance, revocation, role/identity controls and recovery tests
- [ ] D5 concurrency, fault injection, power-loss/filesystem and restore evidence
- [ ] D6 candidate evaluation and unchanged active skill on all failure paths
- [ ] D7 preregistered labeled holdout report, scorer validation, calibration and domain slices
- [ ] D8 OS-level sandbox enforcement and escape tests on every supported platform
- [ ] D9 clean-machine install, offline, backup/restore, upgrade, rollback and uninstall walkthrough
- [ ] D10 verified approver identity/roles, key lifecycle, separation of duties and audit evidence
- [ ] D11 independent security review closed with no unresolved critical/high findings

## Risk and operations
- Threat model revision:
- Known limitations and accepted residual risks:
- Incident response owner and contact:
- Backup/restore evidence location:
- Rollback procedure and verified rollback commit:
- Dependency/SBOM and license review:
- Data retention and privacy review:
- Monitoring and support plan:

## Independent review
- Reviewer identity and organization:
- Review date:
- Report URI/hash:
- Unresolved findings and disposition:

## Owner authorization
- [ ] I reviewed all linked evidence and residual risks.
- [ ] I authorize release of exactly the immutable commit and artifact identified above.
- Owner identity:
- UTC timestamp:
- Signature/approval record URI and digest:

**Default:** NOT APPROVED. Missing evidence, open gates, or unsigned owner authorization blocks release.
