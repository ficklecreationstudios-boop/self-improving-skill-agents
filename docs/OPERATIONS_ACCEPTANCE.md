# Operations acceptance runbook

This runbook is a checklist for the operator performing a clean-machine test. It is not evidence until a dated run record with outputs is attached.

## Record before starting
- Git commit SHA and whether the worktree is clean.
- OS build, architecture, Python version, package-lock hash and Ollama version/model tag (if used).
- Installation destination and backup destination.
- Confirm the active skill directory and audit/archive paths are disposable test data, not production/user data.

## Clean install
1. Create a fresh virtual environment with a supported Python version.
2. Install `requirements-test.lock`, then install the package editable as documented.
3. Run `pytest -q`; preserve full output and exit code.
4. Run `skill-agents --help` and verify each expected command is present.
5. With `OLLAMA_MODEL` unset, run a harmless task and verify it exits as not executed and records a valid audit event rather than returning a model answer.

## Container sandbox integration tests
1. Install Docker Engine and pull the pinned image; the digest is `PINNED_IMAGE` in `src/self_improving_agents/container_capabilities.py`.
2. Set `D8_CONTAINER_TEST_ROOT` to an existing directory on `D:` that Docker can bind-mount.
3. Run `pytest -q -rs tests/test_container_os_sandbox.py tests/test_container_workspace_integration.py tests/test_container_capabilities.py`.
4. Confirm in the output that `test_real_container_enforces_os_sandbox_controls`, `test_real_container_reads_searches_and_rejects_mount_escape` and `test_real_docker_container_integration` **passed**. A skip means the sandbox was not exercised and is not passing evidence.

Behaviour of these three tests, as implemented:
- Docker CLI missing, daemon unavailable, or pinned image not present locally: all three **skip**.
- Docker and image available, but `D8_CONTAINER_TEST_ROOT` unset, not a directory, or not on `D:`: `test_real_container_enforces_os_sandbox_controls` and `test_real_container_reads_searches_and_rejects_mount_escape` **fail** by design, so a configured sandbox run cannot silently skip. `test_real_docker_container_integration` does not use this variable; it creates its workspace inside the repository checkout.
- The tests invoke `docker.exe`. On Linux that executable is not found, so all three skip even when Docker is installed. Linux sandbox verification is not yet supported.

## Backup and restore drill
1. Stop all writers. Copy the skill tree, audit ledger, archive/journal directory, and required configuration to a timestamped backup; do not copy secrets into source control.
2. Record SHA-256 hashes for the backed-up files and verify the audit ledger.
3. Restore into a separate temporary location; never overwrite the original during the drill.
4. Verify restored file hashes and run `skill-agents verify-audit --audit <restored-ledger>`.
5. Run governance recovery against the restored skill/archive/audit paths and preserve the output.
6. Compare before/after skill digests and audit verification results. Any unexplained difference fails the drill.

## Upgrade and rollback drill
1. Use a disposable clone and a pinned commit. Run the full suite before upgrading.
2. Apply the candidate update only to disposable fixture skills with a signed test approval.
3. Simulate an interrupted transaction using the fault-injection tests, then run recovery twice; the second run must be idempotent.
4. Roll back to the prior pinned commit and confirm the suite, skill digests and audit chain verify.
5. Uninstall the editable package from the disposable environment and confirm the command entry point is no longer installed.

## Failure handling
Stop on any missing backup, hash mismatch, invalid audit, unexpected skill mutation, failed test, ambiguous recovery result or unreviewed security finding. Keep failed outputs; do not overwrite them with a rerun.
