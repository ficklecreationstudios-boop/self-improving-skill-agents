"""Command-line entry point."""
import argparse, difflib, json, os, secrets, subprocess, sys, unicodedata
from pathlib import Path
from .models import Task, Proposal, Approval
from .orchestrator import run_task, ModelNotConfiguredError
from .agent_loop import run_agent_task
from .container_capabilities import ContainerCapabilityRegistry
from .skills import discover_skills, select_skills, parse_skill_text
from .audit import AuditLedger
from .agents.review import propose_skill_update
from .governance.approval import Governance, GovernanceError
from .approval_auth import validate_key, key_identifier, ApprovalSignatureError
from .owner_only import restrict_to_current_user
from . import approver_policy, audit_anchor, revocation
from .learning import create_candidate_proposal, write_proposal, load_cases, LearningGateError
from .quality_evaluation import evaluate_file
from .ollama import OllamaAdapter


def read_approval_key(path: str) -> bytes:
    try:
        key = Path(path).read_bytes()
        validate_key(key)
        return key
    except (OSError, ApprovalSignatureError) as exc:
        raise SystemExit(f"Cannot use approval key: {exc}") from exc


PROPOSAL_FIELDS = {"skill_id": str, "base_digest": str, "proposed_content": str, "rationale": str,
                   "proposal_digest": str}
APPROVAL_FIELDS = {"proposal_digest": str, "approver": str, "approved": bool, "reason": str,
                   "signature": str, "key_id": str}


def load_record(path: str, label: str, fields: dict[str, type]) -> dict:
    """Read a proposal or approval JSON file, refusing anything that is not exactly the expected record."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise SystemExit(f"Cannot read {label} file {path}: {exc}") from exc
    if not isinstance(data, dict) or set(data) != set(fields):
        raise SystemExit(f"{label.capitalize()} file {path} must be a JSON object with exactly the fields "
                         f"{', '.join(sorted(fields))}")
    wrong = sorted(name for name, kind in fields.items() if type(data[name]) is not kind)
    if wrong:
        raise SystemExit(f"{label.capitalize()} file {path} has fields of the wrong type: {', '.join(wrong)}")
    return data


def ledger_revocations(path: str) -> list[tuple[str, str]]:
    """(key_id, reason) for every key revocation in a verified audit ledger."""
    if not Path(path).is_file():
        raise SystemExit(f"Audit ledger {path} does not exist; no revocation registry was created")
    ledger = AuditLedger(path)
    if not ledger.verify():
        raise SystemExit(f"Audit ledger {path} failed verification; no revocation registry was created")
    return [(event["payload"].get("key_id"), event["payload"].get("reason") or "imported from audit ledger")
            for event in ledger._events() if event.get("type") == "approval_key_revoked"]


def printable(text: str) -> str:
    """Show control and invisible formatting characters (terminal escapes, bidi overrides) as visible escapes."""
    return "".join(char if char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cf", "Zl", "Zp"}
                   else f"\\u{ord(char):04x}" for char in text)


def show_for_review(proposal: Proposal, target: Path, current: str) -> None:
    """Print the current skill, its proposed replacement and a line diff, so the signer sees what changes."""
    rule = "=" * 72
    diff = list(difflib.unified_diff(current.split("\n"), proposal.proposed_content.split("\n"),
                                     "current", "proposed", lineterm=""))
    print("\n".join([
        rule, f"Proposal {proposal.proposal_digest}", f"Skill: {proposal.skill_id} ({target})",
        f"Rationale: {printable(proposal.rationale)}",
        rule, "CURRENT SKILL", rule, printable(current),
        rule, "PROPOSED REPLACEMENT", rule, printable(proposal.proposed_content),
        rule, "CHANGES (current -> proposed)", rule, *([printable(line) for line in diff] or ["(no changes)"]),
        rule,
    ]))


def model_output_label(model: str | None) -> str:
    return f"Model output (Ollama model {model!r}), not fact-checked:"


def main() -> None:
    parser = argparse.ArgumentParser(prog="skill-agents")
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="Run a task using selected local skills")
    ask.add_argument("text"); ask.add_argument("--domain", default="general"); ask.add_argument("--skills", default="skills"); ask.add_argument("--audit", default="data/audit.jsonl")
    agent = sub.add_parser("agent", help="Run a bounded agent loop with allowlisted local capabilities")
    agent.add_argument("text"); agent.add_argument("--workspace", required=True, help="Explicit directory mounted read-only into the agent container"); agent.add_argument("--skills", default="skills")
    agent.add_argument("--domain", default="general"); agent.add_argument("--audit", default="data/audit.jsonl")
    agent.add_argument("--max-steps", type=int, default=4)
    evaluate = sub.add_parser("evaluate-quality", help="Evaluate model outputs against preregistered thresholds")
    evaluate.add_argument("--cases", required=True); evaluate.add_argument("--thresholds", required=True)
    evaluate.add_argument("--skills", default="skills"); evaluate.add_argument("--audit", default="data/evaluation-audit.jsonl")
    evaluate.add_argument("--output", required=True)
    audit = sub.add_parser("verify-audit", help="Verify the hash-chain audit ledger"); audit.add_argument("--audit", default="data/audit.jsonl")
    audit.add_argument("--anchor-seq", type=int, help="Also require this event, as noted outside the machine")
    audit.add_argument("--anchor-hash", help="The event_hash noted for --anchor-seq")
    anchor = sub.add_parser("anchor-audit", help="Remember the ledger's last hash outside it, so a rewrite can be noticed")
    anchor.add_argument("--audit", default="data/audit.jsonl")
    add_approver = sub.add_parser("add-approver", help="List an approval key and name; once a list exists, only listed pairs may approve")
    add_approver.add_argument("--key-file", required=True); add_approver.add_argument("--name", required=True)
    sub.add_parser("list-approvers", help="Show the approver policy")
    recover_audit = sub.add_parser("recover-audit", help="Repair a torn final audit line after a crash, preserving the original"); recover_audit.add_argument("--audit", default="data/audit.jsonl")
    recover = sub.add_parser("recover", help="Recover interrupted skill updates from transaction journals")
    recover.add_argument("--skills", default="skills"); recover.add_argument("--archive", default="data/skill-archive"); recover.add_argument("--audit", default="data/audit.jsonl")
    bench = sub.add_parser("benchmark", help="Compare skill context proxy")
    bench.add_argument("text"); bench.add_argument("--domain", default="general"); bench.add_argument("--skills", default="skills")
    proposal = sub.add_parser("propose", help="Create an inert, digest-bound skill-update proposal")
    proposal.add_argument("skill_id"); proposal.add_argument("proposed_content_file"); proposal.add_argument("--rationale", required=True); proposal.add_argument("--skills", default="skills"); proposal.add_argument("--output")
    learn = sub.add_parser("learn-from-feedback", help="Generate and screen an inert skill proposal using local Ollama")
    learn.add_argument("--skill-id", required=True); learn.add_argument("--task-id", required=True)
    learn.add_argument("--task", required=True); learn.add_argument("--output-text", required=True)
    learn.add_argument("--rating", required=True, type=int); learn.add_argument("--feedback", required=True)
    learn.add_argument("--skills", default="skills"); learn.add_argument("--audit", default="data/audit.jsonl")
    learn.add_argument("--holdout", required=True, help="Path to frozen JSONL regression cases")
    learn.add_argument("--proposal-output", required=True); learn.add_argument("--max-chars", type=int, default=20000)
    init_key = sub.add_parser("init-approval-key", help="Create a random local shared-secret approval key")
    init_key.add_argument("key_file")
    init_registry = sub.add_parser("init-revocation-registry",
                                   help="Create the per-user approval-key revocation registry (once; never overwritten)")
    init_registry.add_argument("--import-audit", action="append", default=[], metavar="AUDIT_FILE",
                               help="Carry over key revocations from this verified audit ledger (repeatable)")
    approve = sub.add_parser("approve-proposal", help="Sign a proposal approval using the local shared secret")
    approve.add_argument("proposal_file"); approve.add_argument("--key-file", required=True)
    approve.add_argument("--approver", required=True); approve.add_argument("--reason", required=True)
    approve.add_argument("--approval-output", required=True); approve.add_argument("--approve", action="store_true", required=True)
    approve.add_argument("--audit", default="data/audit.jsonl")
    approve.add_argument("--archive", default="data/skill-archive", help="Must match the archive path used by apply-proposal")
    approve.add_argument("--skills", default="skills", help="Skill root holding the skill to review; must match apply-proposal")
    revoke = sub.add_parser("revoke-approval-key", help="Revoke an approval key identifier in the audit ledger")
    revoke.add_argument("key_id", help="Full SHA-256 key identifier printed by init-approval-key")
    revoke.add_argument("--reason", required=True); revoke.add_argument("--audit", default="data/audit.jsonl")
    revoke.add_argument("--archive", default="data/skill-archive", help="Must match the archive path used by apply-proposal")
    apply = sub.add_parser("apply-proposal", help="Apply a proposal with a valid signed approval")
    apply.add_argument("proposal_file"); apply.add_argument("approval_file")
    apply.add_argument("--key-file", required=True); apply.add_argument("--skills", default="skills")
    apply.add_argument("--archive", default="data/skill-archive"); apply.add_argument("--audit", default="data/audit.jsonl")
    args = parser.parse_args()
    if args.command == "ask":
        try:
            result = run_task(Task(args.text, args.domain), args.skills, args.audit)
        except (ModelNotConfiguredError, ValueError) as exc:  # ValueError: refused Ollama settings
            raise SystemExit(str(exc)) from exc
        print(model_output_label(result.model), file=sys.stderr)
        print(result.output)
        print(json.dumps({"skills": result.skill_ids, "generated_by": {"provider": "ollama", "model": result.model},
                          "review": result.review.__dict__, "task_digest": result.task_digest,
                          "output_digest": result.output_digest}, indent=2))
    elif args.command == "agent":
        try:
            selected = select_skills(args.text, args.domain, discover_skills(args.skills))
            adapter = OllamaAdapter()
            result = run_agent_task(Task(args.text, args.domain), ContainerCapabilityRegistry(args.workspace),
                                    args.audit, adapter, max_steps=args.max_steps, skills=selected)
        except (RuntimeError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
        if result.stop_reason == "final_answer":
            print(model_output_label(getattr(adapter, "model", None)), file=sys.stderr)
        print(result.output)
        print(json.dumps({"skill_ids": [skill.skill_id for skill in selected],
                          "tool_call_count": len(result.tool_calls), "tool_names": [call["name"] for call in result.tool_calls],
                          "steps": result.steps, "stop_reason": result.stop_reason,
                          "task_digest": result.task_digest, "output_digest": result.output_digest}, indent=2))
        if result.stop_reason != "final_answer":
            raise SystemExit(
                f"Agent stopped without a valid final answer: {result.stop_reason}"
            )
    elif args.command == "evaluate-quality":
        try:
            report = evaluate_file(args.cases, args.skills, args.audit, OllamaAdapter(),
                                   args.output, args.thresholds)
        except (RuntimeError, ValueError, OSError) as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps({key: value for key, value in report.items() if key != "cases"}, indent=2))
        print(f"Full per-case report written to {args.output}")
    elif args.command == "verify-audit":
        if (args.anchor_seq is None) != (args.anchor_hash is None):
            raise SystemExit("--anchor-seq and --anchor-hash must be given together")
        ledger = AuditLedger(args.audit)
        if not ledger.verify():
            print("INVALID")
        else:
            try:
                problems = audit_anchor.anchor_problems(args.audit)
            except audit_anchor.AuditAnchorError as exc:
                problems = [str(exc)]
            if args.anchor_seq is not None:
                problem = audit_anchor.check_event(ledger._events(), args.anchor_seq, args.anchor_hash)
                problems += [problem] if problem else []
            if problems:
                print("INVALID: " + "; ".join(problems))
                raise SystemExit(2)
            print("VALID")
    elif args.command == "anchor-audit":
        try:
            entry = audit_anchor.record_anchor(args.audit)
        except audit_anchor.AuditAnchorError as exc:
            raise SystemExit(f"anchor-audit failed: {exc}") from exc
        print(json.dumps({"status": "anchored", "seq": entry["seq"], "event_hash": entry["event_hash"],
                          "note": "Also keep this hash somewhere off this computer; check it with verify-audit --anchor-seq and --anchor-hash."}, indent=2))
    elif args.command == "add-approver":
        try:
            print(json.dumps(approver_policy.add_approver(key_identifier(read_approval_key(args.key_file)), args.name), indent=2))
        except approver_policy.ApproverPolicyError as exc:
            raise SystemExit(f"add-approver failed: {exc}") from exc
    elif args.command == "list-approvers":
        try:
            print(json.dumps(approver_policy.list_approvers(), indent=2))
        except approver_policy.ApproverPolicyError as exc:
            raise SystemExit(f"list-approvers failed: {exc}") from exc
    elif args.command == "recover-audit":
        result = AuditLedger(args.audit).recover_torn_tail()
        print(json.dumps(result, indent=2))
        if result["status"] == "refused":
            raise SystemExit(2)
    elif args.command == "recover":
        results = Governance(args.skills, args.archive, AuditLedger(args.audit)).recover_pending()
        print(json.dumps({"recovered": results, "audit_valid": AuditLedger(args.audit).verify()}, indent=2))
    elif args.command == "benchmark":
        from .benchmark import compare_context
        skills = discover_skills(args.skills); selected = select_skills(args.text, args.domain, skills)
        print(json.dumps(compare_context(args.text, skills, selected), indent=2))
    elif args.command == "propose":
        matches = [s for s in discover_skills(args.skills) if s.skill_id == args.skill_id]
        if len(matches) != 1: raise SystemExit(f"Expected exactly one skill with id {args.skill_id!r}; found {len(matches)}")
        current = Path(matches[0].path).read_text(encoding="utf-8")
        proposed = Path(args.proposed_content_file).read_text(encoding="utf-8")
        parsed = parse_skill_text(proposed, Path(matches[0].path).parent.name)
        if parsed is None or parsed.skill_id != args.skill_id:
            raise SystemExit(f"Proposed content is not a valid SKILL.md for skill id {args.skill_id!r}; no proposal was created")
        item = propose_skill_update(args.skill_id, current, proposed, args.rationale)
        destination = Path(args.output or f"data/proposals/{args.skill_id}.json")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({**item.payload(), "proposal_digest": item.proposal_digest}, indent=2), encoding="utf-8")
        print(json.dumps({"proposal_file": str(destination), "proposal_digest": item.proposal_digest, "status": "proposal_created_not_applied"}, indent=2))
    elif args.command == "learn-from-feedback":
        try:
            item, structural, behavioral = create_candidate_proposal(
                skill_id=args.skill_id, skill_root=args.skills, task_id=args.task_id,
                task_text=args.task, output_text=args.output_text, rating=args.rating,
                feedback=args.feedback, adapter=OllamaAdapter(), ledger=AuditLedger(args.audit),
                holdout_cases=load_cases(args.holdout), max_chars=args.max_chars,
            )
        except LearningGateError as exc:
            raise SystemExit(str(exc)) from exc
        destination = write_proposal(item, args.proposal_output)
        print(json.dumps({"status": "proposal_created_not_applied", "proposal_file": str(destination),
                          "proposal_digest": item.proposal_digest, "structural_screening": structural.as_dict(),
                          "regression_screening": behavioral.as_dict(),
                          "warning": "Substring regression checks are not semantic quality validation; independent review and human approval remain required."}, indent=2))
    elif args.command == "init-approval-key":
        destination = Path(args.key_file); destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            destination.open("xb").close()  # restrict the empty file before any key bytes exist
        except FileExistsError:
            raise SystemExit("Refusing to overwrite an existing approval key")
        try:
            restrict_to_current_user(destination)
            with destination.open("r+b") as stream:
                stream.write(secrets.token_bytes(32)); stream.flush(); os.fsync(stream.fileno())
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            destination.unlink(missing_ok=True)
            raise SystemExit(f"Could not restrict the approval key to the current user; no key was created: {exc}")
        print(json.dumps({"status": "key_created", "path": str(destination),
                          "key_id": key_identifier(destination.read_bytes()),
                          "warning": "Protect this key outside the repository; anyone holding it can sign approvals. The key ID is a public fingerprint, not the key."}, indent=2))
    elif args.command == "init-revocation-registry":
        imported = [item for path in args.import_audit for item in ledger_revocations(path)]
        try:
            result = revocation.init_registry(imported)
        except revocation.RevocationRegistryError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps({**result, "imported_from": args.import_audit}, indent=2))
    elif args.command == "approve-proposal":
        key = read_approval_key(args.key_file)
        item = Proposal(**json.loads(Path(args.proposal_file).read_text(encoding="utf-8")))
        if item.sealed().proposal_digest != item.proposal_digest:
            raise SystemExit("Proposal digest is invalid; refusing to sign")
        governance = Governance(args.skills, args.archive, AuditLedger(args.audit), approval_key=key)
        try:
            governance.check_key_active()
            target, current = governance.current_skill_for(item)
        except GovernanceError as exc:
            raise SystemExit(f"{exc}; nothing was signed") from exc
        show_for_review(item, target, current)
        try:
            typed = input(f"Type the skill id '{item.skill_id}' to sign this approval; anything else cancels: ")
        except EOFError:
            typed = None
        if typed != item.skill_id:
            raise SystemExit("Confirmation did not match the skill id; nothing was signed")
        try:
            if governance.current_skill_for(item)[1] != current:
                raise GovernanceError("Stale proposal: the skill changed while it was being reviewed")
            # Checks the ledger and the per-user registry for revocation, then records the signature.
            approval = governance.issue_approval(item, args.approver, True, args.reason)
        except GovernanceError as exc:
            raise SystemExit(f"{exc}; nothing was signed") from exc
        destination = Path(args.approval_output); destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(approval.__dict__, indent=2), encoding="utf-8")
        print(json.dumps({"status": "signed_approval_created", "approval_file": str(destination),
                          "proposal_digest": item.proposal_digest, "key_id": approval.key_id}, indent=2))
    elif args.command == "revoke-approval-key":
        ledger = AuditLedger(args.audit)
        try:
            result = Governance(".", args.archive, ledger).revoke_approval_key(args.key_id, args.reason)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(result, indent=2))
    elif args.command == "apply-proposal":
        key = read_approval_key(args.key_file)
        item = Proposal(**load_record(args.proposal_file, "proposal", PROPOSAL_FIELDS))
        approval = Approval(**load_record(args.approval_file, "approval", APPROVAL_FIELDS))
        ledger = AuditLedger(args.audit)
        try:
            target = Governance(args.skills, args.archive, ledger, approval_key=key).apply(item, approval)
        except GovernanceError as exc:
            # Expected refusals only; any other exception keeps its traceback so real bugs stay visible.
            raise SystemExit(f"apply-proposal failed: {exc}") from exc
        print(json.dumps({"status": "applied", "skill_id": item.skill_id, "path": str(target),
                          "proposal_digest": item.proposal_digest, "audit_valid": ledger.verify()}, indent=2))

if __name__ == "__main__": main()
