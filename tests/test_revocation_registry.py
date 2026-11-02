import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from self_improving_agents import revocation
from self_improving_agents.agents.review import propose_skill_update
from self_improving_agents.approval_auth import key_identifier
from self_improving_agents.audit import AuditLedger
from self_improving_agents.cli import main
from self_improving_agents.governance.approval import Governance, GovernanceError
from self_improving_agents.models import digest_text
from self_improving_agents.owner_only import owner_only_problem, sddl_problem

KEY = b"test-only-approval-key-material-32-bytes-minimum!!"
OLD = "---\nid: demo\nname: Demo\ndomain: general\ntags: []\n---\nold body\n"
NEW = OLD.replace("old body", "new body")
ME = "S-1-5-21-1-2-3-1001"


def run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["skill-agents", *argv])
    monkeypatch.setattr("builtins.input", lambda prompt="": "demo")
    main()


def make_skill(tmp_path):
    folder = tmp_path / "skills" / "demo"; folder.mkdir(parents=True)
    target = folder / "SKILL.md"; target.write_bytes(OLD.encode("utf-8"))
    return target


def signed_setup(tmp_path):
    target = make_skill(tmp_path)
    ledger = AuditLedger(tmp_path / "audit.jsonl")
    gov = Governance(tmp_path / "skills", tmp_path / "archive", ledger, approval_key=KEY)
    proposal = propose_skill_update("demo", OLD, NEW, "registry test")
    return target, ledger, gov, proposal, gov.issue_approval(proposal, "me", True, "reviewed")


@pytest.fixture
def private_registry(tmp_path, monkeypatch):
    directory = tmp_path / "profile" / revocation.APP_DIRECTORY
    monkeypatch.setattr(revocation, "registry_dir", lambda: directory)
    return directory


def grant_everyone_read(path, directory=False):
    if os.name == "nt":
        subprocess.run(["icacls", str(path), "/grant", "*S-1-1-0:(R)"], capture_output=True, check=True)
    else:
        path.chmod(0o755 if directory else 0o644)


def test_revoking_in_one_ledger_blocks_signing_and_applying_with_any_other_ledger(tmp_path, monkeypatch):
    """The audit's ledger-switching attack, end to end through the CLI."""
    monkeypatch.chdir(tmp_path)
    target = make_skill(tmp_path)
    (tmp_path / "new.md").write_bytes(NEW.encode("utf-8"))
    key = tmp_path / "keys" / "operator.approval-key"
    run_cli(monkeypatch, "init-approval-key", str(key))
    key_id = key_identifier(key.read_bytes())
    run_cli(monkeypatch, "propose", "demo", "new.md", "--rationale", "probe", "--output", "p.json")
    run_cli(monkeypatch, "approve-proposal", "p.json", "--key-file", str(key), "--approver", "me",
            "--reason", "r", "--approve", "--approval-output", "a.json", "--audit", "A.jsonl")
    run_cli(monkeypatch, "revoke-approval-key", key_id, "--reason", "compromised", "--audit", "A.jsonl")

    for ledger in ("A.jsonl", "B.jsonl"):
        with pytest.raises(SystemExit, match="revoked"):
            run_cli(monkeypatch, "apply-proposal", "p.json", "a.json", "--key-file", str(key),
                    "--audit", ledger)
        with pytest.raises(SystemExit, match="revoked"):
            run_cli(monkeypatch, "approve-proposal", "p.json", "--key-file", str(key), "--approver", "me",
                    "--reason", "r", "--approve", "--approval-output", "again.json", "--audit", ledger)
    assert target.read_text(encoding="utf-8") == OLD
    assert not (tmp_path / "again.json").exists()
    assert key_id in revocation.revoked_key_ids()


def test_revocation_through_the_api_holds_for_a_fresh_ledger_and_archive(tmp_path):
    target, _, gov, proposal, approval = signed_setup(tmp_path)
    gov.revoke_approval_key(approval.key_id, "rotation")
    elsewhere = Governance(tmp_path / "skills", tmp_path / "other-archive",
                           AuditLedger(tmp_path / "fresh.jsonl"), approval_key=KEY)
    with pytest.raises(GovernanceError, match="revoked"):
        elsewhere.issue_approval(proposal, "me", True, "after revocation")
    with pytest.raises(GovernanceError, match="revoked"):
        elsewhere.apply(proposal, approval)
    assert target.read_text(encoding="utf-8") == OLD


def test_signing_records_the_approval_in_the_ledger(tmp_path):
    _, ledger, _, proposal, approval = signed_setup(tmp_path)
    signed = [event["payload"] for event in ledger._events() if event["type"] == "proposal_approval_signed"]
    assert signed == [{"proposal_digest": proposal.proposal_digest, "approver": "me", "key_id": approval.key_id,
                       "approval_signature_digest": digest_text(approval.signature), "reason": "reviewed",
                       "authorized_by": "single_operator_default"}]


def test_apply_requires_a_matching_signed_record_in_the_selected_ledger(tmp_path):
    target, _, gov, proposal, approval = signed_setup(tmp_path)
    other_ledger = AuditLedger(tmp_path / "other.jsonl")
    other = Governance(tmp_path / "skills", tmp_path / "archive", other_ledger, approval_key=KEY)
    with pytest.raises(GovernanceError, match="no matching approval-signed record"):
        other.apply(proposal, approval)
    # A record naming the proposal and key but a different signature does not count.
    other_ledger.append("proposal_approval_signed", {"proposal_digest": proposal.proposal_digest,
                                                     "key_id": approval.key_id,
                                                     "approval_signature_digest": "0" * 64})
    with pytest.raises(GovernanceError, match="no matching approval-signed record"):
        other.apply(proposal, approval)
    assert target.read_text(encoding="utf-8") == OLD
    assert list((tmp_path / "archive").glob("*.SKILL.md")) == []
    gov.apply(proposal, approval)
    assert target.read_text(encoding="utf-8") == NEW


def _break_missing(path, monkeypatch):
    path.unlink()


def _break_corrupt_json(path, monkeypatch):
    path.write_text("{not json", encoding="utf-8")


def _break_edited_entry(path, monkeypatch):
    document = json.loads(path.read_text(encoding="utf-8"))
    document["revocations"].append({"key_id": "a" * 64, "reason": "edited by hand", "revoked_at": "x"})
    path.write_text(json.dumps(document), encoding="utf-8")


def _break_wrong_schema(path, monkeypatch):
    document = json.loads(path.read_text(encoding="utf-8"))
    document["schema"] = 2
    path.write_text(json.dumps(document), encoding="utf-8")


def _break_unreadable(path, monkeypatch):
    def refuse(_):
        raise PermissionError("injected read failure")
    monkeypatch.setattr(revocation, "_read_bytes", refuse)


def _break_file_permissions(path, monkeypatch):
    grant_everyone_read(path)


def _break_folder_permissions(path, monkeypatch):
    grant_everyone_read(path.parent, directory=True)


@pytest.mark.parametrize("damage, reason", [
    (_break_missing, "is missing"),
    (_break_corrupt_json, "unreadable or corrupt"),
    (_break_edited_entry, "failed its digest check"),
    (_break_wrong_schema, "invalid structure"),
    (_break_unreadable, "unreadable or corrupt"),
    (_break_file_permissions, "not owner-only"),
    (_break_folder_permissions, "not owner-only"),
], ids=lambda value: value.__name__[7:] if callable(value) else "")
def test_damaged_registry_fails_closed_for_sign_apply_and_revoke(tmp_path, monkeypatch, private_registry,
                                                                  damage, reason):
    revocation.init_registry()
    target, ledger, gov, proposal, approval = signed_setup(tmp_path)
    before = ledger.path.read_bytes()
    damage(revocation.registry_path(), monkeypatch)
    with pytest.raises(GovernanceError, match=reason):
        gov.issue_approval(proposal, "me", True, "while damaged")
    with pytest.raises(GovernanceError, match=reason):
        gov.apply(proposal, approval)
    with pytest.raises(GovernanceError, match=reason):
        gov.revoke_approval_key(approval.key_id, "while damaged")
    assert target.read_text(encoding="utf-8") == OLD
    assert ledger.path.read_bytes() == before
    if damage is _break_missing:
        assert not revocation.registry_path().exists()


@pytest.mark.parametrize("failure", ["replace", "temp_not_owner_only"])
def test_registry_that_cannot_be_safely_updated_blocks_revocation_without_partial_state(
        tmp_path, monkeypatch, private_registry, failure):
    revocation.init_registry()
    _, ledger, gov, proposal, approval = signed_setup(tmp_path)
    registry_before = revocation.registry_path().read_bytes()
    ledger_before = ledger.path.read_bytes()
    with monkeypatch.context() as injected:
        if failure == "replace":
            def refuse(*args, **kwargs):
                raise OSError("injected replace failure")
            injected.setattr(revocation.os, "replace", refuse)
        else:
            real = revocation.owner_only_problem
            injected.setattr(revocation, "owner_only_problem",
                             lambda path, **kw: "injected" if path.name.endswith(".tmp") else real(path, **kw))
        with pytest.raises(GovernanceError, match="registry"):
            gov.revoke_approval_key(approval.key_id, "rotation")
    assert revocation.registry_path().read_bytes() == registry_before
    assert ledger.path.read_bytes() == ledger_before
    assert not list(private_registry.glob("*.tmp"))
    assert approval.key_id not in revocation.revoked_key_ids()


def test_registry_is_never_recreated_implicitly(tmp_path, private_registry):
    revocation.init_registry()
    _, _, gov, proposal, approval = signed_setup(tmp_path)
    revocation.registry_path().unlink()
    for attempt in (lambda: gov.revoke_approval_key(approval.key_id, "rotation"),
                    lambda: gov.issue_approval(proposal, "me", True, "again"),
                    lambda: gov.apply(proposal, approval)):
        with pytest.raises(GovernanceError, match="missing"):
            attempt()
        assert not revocation.registry_path().exists()
    assert revocation.init_registry()["status"] == "registry_created"
    with pytest.raises(revocation.RevocationRegistryError, match="never recreated"):
        revocation.init_registry()


def test_init_imports_revocations_from_verified_ledgers_only(tmp_path, monkeypatch, private_registry):
    good = AuditLedger(tmp_path / "old.jsonl")
    good.append("approval_key_revoked", {"key_id": "b" * 64, "reason": "rotated last year"})
    bad = tmp_path / "bad.jsonl"; bad.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="failed verification"):
        run_cli(monkeypatch, "init-revocation-registry", "--import-audit", str(good.path), "--import-audit", str(bad))
    with pytest.raises(SystemExit, match="does not exist"):
        run_cli(monkeypatch, "init-revocation-registry", "--import-audit", str(tmp_path / "absent.jsonl"))
    assert not revocation.registry_path().exists()
    run_cli(monkeypatch, "init-revocation-registry", "--import-audit", str(good.path))
    assert revocation.revoked_key_ids() == {"b" * 64}
    with pytest.raises(SystemExit, match="never recreated"):
        run_cli(monkeypatch, "init-revocation-registry")


def test_init_creates_an_owner_only_folder_and_file(private_registry):
    revocation.init_registry()
    path = revocation.registry_path()
    assert owner_only_problem(path.parent, directory=True) is None
    assert owner_only_problem(path) is None
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600 and path.parent.stat().st_mode & 0o777 == 0o700
        return
    me = subprocess.run(["whoami"], capture_output=True, text=True, check=True).stdout.strip().casefold()

    def aces(target):
        listing = subprocess.run(["icacls", str(target)], capture_output=True, text=True, check=True).stdout
        lines = listing.split("\n\n")[0].splitlines()
        return [line.replace(str(target), "").strip().casefold() for line in lines if line.strip()]

    assert aces(path.parent) == [f"{me}:(oi)(ci)(f)"]
    assert aces(path) == [f"{me}:(i)(f)"]


def test_registry_location_comes_from_the_os_profile_not_environment(tmp_path, monkeypatch):
    real = revocation._known_local_appdata()
    for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(name, str(tmp_path))
    assert revocation._known_local_appdata() == real
    assert tmp_path not in real.parents


def test_revoke_completes_a_ledger_only_revocation_and_is_then_idempotent(tmp_path):
    _, ledger, gov, _, approval = signed_setup(tmp_path)
    ledger.append("approval_key_revoked", {"key_id": approval.key_id, "reason": "recorded before the registry"})
    assert approval.key_id not in revocation.revoked_key_ids()
    assert gov.revoke_approval_key(approval.key_id, "carry over")["status"] == "key_revoked"
    assert approval.key_id in revocation.revoked_key_ids()
    assert gov.revoke_approval_key(approval.key_id, "repeat")["status"] == "already_revoked"
    assert sum(event["type"] == "approval_key_revoked" for event in ledger._events()) == 1


def test_concurrent_revocations_through_different_archives_are_all_kept(tmp_path):
    key_ids = [key_identifier(bytes([n]) * 40) for n in range(1, 7)]

    def revoke(index):
        gov = Governance(tmp_path / "skills", tmp_path / f"archive-{index}",
                         AuditLedger(tmp_path / f"audit-{index}.jsonl"))
        return gov.revoke_approval_key(key_ids[index], "rotation")["status"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        statuses = list(pool.map(revoke, range(6), timeout=60))
    assert statuses == ["key_revoked"] * 6
    assert revocation.revoked_key_ids() == set(key_ids)


@pytest.mark.parametrize("sddl, problem", [
    (f"O:{ME}D:PAI(A;OICI;FA;;;{ME})", None),
    (f"O:{ME}D:AI(A;ID;FA;;;{ME})", None),
    (f"O:BAD:PAI(A;;FA;;;{ME})", "owner"),
    (f"O:{ME}D:PAI(A;;FA;;;{ME})(A;;FR;;;WD)", "another principal"),
    (f"O:{ME}D:PAI(D;;FA;;;WD)(A;;FA;;;{ME})", "another principal"),
    (f"O:{ME}D:NO_ACCESS_CONTROL", "no entries"),
    (f"O:{ME}", "no access-control list"),
])
def test_sddl_check_accepts_only_owner_only_descriptors(sddl, problem):
    result = sddl_problem(sddl, ME)
    assert (result is None) if problem is None else (problem in result)
