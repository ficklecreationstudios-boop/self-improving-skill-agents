"""Command-line entry point."""
import argparse, json, os, secrets, re
from pathlib import Path
from .models import Task, Proposal, Approval
from .orchestrator import run_task, ModelNotConfiguredError
from .agent_loop import run_agent_task
from .container_capabilities import ContainerCapabilityRegistry
from .skills import discover_skills, select_skills
from .audit import AuditLedger
from .agents.review import propose_skill_update
from .governance.approval import Governance
from .approval_auth import sign_approval, validate_key, key_identifier, ApprovalSignatureError
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
    approve = sub.add_parser("approve-proposal", help="Sign a proposal approval using the local shared secret")
    approve.add_argument("proposal_file"); approve.add_argument("--key-file", required=True)
    approve.add_argument("--approver", required=True); approve.add_argument("--reason", required=True)
    approve.add_argument("--approval-output", required=True); approve.add_argument("--approve", action="store_true", required=True)
    approve.add_argument("--audit", default="data/audit.jsonl")
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
        except ModelNotConfiguredError as exc:
            raise SystemExit(str(exc)) from exc
        print(result.output)
        print(json.dumps({"skills": result.skill_ids, "review": result.review.__dict__, "task_digest": result.task_digest, "output_digest": result.output_digest}, indent=2))
    elif args.command == "agent":
        try:
            selected = select_skills(args.text, args.domain, discover_skills(args.skills))
            result = run_agent_task(Task(args.text, args.domain), ContainerCapabilityRegistry(args.workspace),
                                    args.audit, OllamaAdapter(), max_steps=args.max_steps, skills=selected)
        except (RuntimeError, ValueError) as exc:
            raise SystemExit(str(exc)) from exc
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
    elif args.command == "verify-audit": print("VALID" if AuditLedger(args.audit).verify() else "INVALID")
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
            with destination.open("xb") as stream:
                stream.write(secrets.token_bytes(32)); stream.flush(); os.fsync(stream.fileno())
            if os.name != "nt": destination.chmod(0o600)
        except FileExistsError:
            raise SystemExit("Refusing to overwrite an existing approval key")
        print(json.dumps({"status": "key_created", "path": str(destination),
                          "key_id": key_identifier(destination.read_bytes()),
                          "warning": "Protect this key outside the repository; anyone holding it can sign approvals. The key ID is a public fingerprint, not the key."}, indent=2))
    elif args.command == "approve-proposal":
        key = read_approval_key(args.key_file)
        ledger = AuditLedger(args.audit)
        if not ledger.verify():
            raise SystemExit("Audit ledger is invalid; refusing to sign")
        key_id = key_identifier(key)
        if any(event.get("type") == "approval_key_revoked"
               and event.get("payload", {}).get("key_id") == key_id
               for event in ledger._events()):
            raise SystemExit("Approval key is revoked; refusing to sign")
        item = Proposal(**json.loads(Path(args.proposal_file).read_text(encoding="utf-8")))
        if item.sealed().proposal_digest != item.proposal_digest:
            raise SystemExit("Proposal digest is invalid; refusing to sign")
        try:
            approval = sign_approval(Approval(item.proposal_digest, args.approver, True, args.reason), key)
        except ApprovalSignatureError as exc:
            raise SystemExit(str(exc)) from exc
        destination = Path(args.approval_output); destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(approval.__dict__, indent=2), encoding="utf-8")
        ledger.append("proposal_approval_signed", {
            "proposal_digest": item.proposal_digest, "approver": approval.approver,
            "key_id": approval.key_id, "approval_signature_digest": __import__("hashlib").sha256(approval.signature.encode("utf-8")).hexdigest(),
            "reason": approval.reason,
        })
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
        item = Proposal(**json.loads(Path(args.proposal_file).read_text(encoding="utf-8")))
        approval = Approval(**json.loads(Path(args.approval_file).read_text(encoding="utf-8")))
        ledger = AuditLedger(args.audit)
        target = Governance(args.skills, args.archive, ledger, approval_key=key).apply(item, approval)
        print(json.dumps({"status": "applied", "skill_id": item.skill_id, "path": str(target),
                          "proposal_digest": item.proposal_digest, "audit_valid": ledger.verify()}, indent=2))

if __name__ == "__main__": main()
