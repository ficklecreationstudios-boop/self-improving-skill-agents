"""Command-line entry point."""
import argparse, json
from pathlib import Path
from .models import Task, Proposal
from .orchestrator import run_task
from .skills import discover_skills, select_skills
from .audit import AuditLedger
from .agents.review import propose_skill_update
from .governance.approval import Governance
from .learning import create_candidate_proposal, write_proposal, LearningGateError
from .ollama import OllamaAdapter

def main() -> None:
    parser = argparse.ArgumentParser(prog="skill-agents")
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="Run a task using selected local skills")
    ask.add_argument("text"); ask.add_argument("--domain", default="general"); ask.add_argument("--skills", default="skills"); ask.add_argument("--audit", default="data/audit.jsonl")
    audit = sub.add_parser("verify-audit", help="Verify the hash-chain audit ledger"); audit.add_argument("--audit", default="data/audit.jsonl")
    bench = sub.add_parser("benchmark", help="Compare skill context proxy")
    bench.add_argument("text"); bench.add_argument("--domain", default="general"); bench.add_argument("--skills", default="skills")
    proposal = sub.add_parser("propose", help="Create an inert, digest-bound skill-update proposal")
    proposal.add_argument("skill_id"); proposal.add_argument("proposed_content_file"); proposal.add_argument("--rationale", required=True); proposal.add_argument("--skills", default="skills"); proposal.add_argument("--output")
    learn = sub.add_parser("learn-from-feedback", help="Use local Ollama to create a screened, inert skill proposal")
    learn.add_argument("--skill-id", required=True); learn.add_argument("--task-id", required=True)
    learn.add_argument("--task", required=True); learn.add_argument("--output-text", required=True)
    learn.add_argument("--rating", required=True, type=int); learn.add_argument("--feedback", required=True)
    learn.add_argument("--skills", default="skills"); learn.add_argument("--audit", default="data/audit.jsonl")
    learn.add_argument("--proposal-output", required=True); learn.add_argument("--max-chars", type=int, default=20000)
    apply = sub.add_parser("apply-proposal", help="Apply a proposal after explicit human approval")
    apply.add_argument("proposal_file"); apply.add_argument("--skills", default="skills"); apply.add_argument("--archive", default="data/skill-archive"); apply.add_argument("--audit", default="data/audit.jsonl"); apply.add_argument("--approver", required=True); apply.add_argument("--approve", action="store_true", required=True); apply.add_argument("--reason", default="")
    args = parser.parse_args()
    if args.command == "ask":
        result = run_task(Task(args.text, args.domain), args.skills, args.audit)
        print(result.output)
        print(json.dumps({"skills": result.skill_ids, "review": result.review.__dict__, "task_digest": result.task_digest, "output_digest": result.output_digest}, indent=2))
    elif args.command == "verify-audit": print("VALID" if AuditLedger(args.audit).verify() else "INVALID")
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
            item, evaluation = create_candidate_proposal(
                skill_id=args.skill_id, skill_root=args.skills, task_id=args.task_id,
                task_text=args.task, output_text=args.output_text, rating=args.rating,
                feedback=args.feedback, adapter=OllamaAdapter(), ledger=AuditLedger(args.audit),
                max_chars=args.max_chars,
            )
        except LearningGateError as exc:
            raise SystemExit(str(exc)) from exc
        destination = write_proposal(item, args.proposal_output)
        print(json.dumps({
            "status": "proposal_created_not_applied", "proposal_file": str(destination),
            "proposal_digest": item.proposal_digest, "screening": evaluation.as_dict(),
            "warning": "Mechanical screening is not semantic quality validation; independent evaluation and human approval remain required.",
        }, indent=2))
    elif args.command == "apply-proposal":
        data = json.loads(Path(args.proposal_file).read_text(encoding="utf-8"))
        item = Proposal(**data)
        ledger = AuditLedger(args.audit)
        governance = Governance(args.skills, args.archive, ledger)
        approval = governance.issue_approval(item, args.approver, approved=args.approve, reason=args.reason)
        target = governance.apply(item, approval)
        print(json.dumps({"status": "applied", "skill_id": item.skill_id, "path": str(target), "proposal_digest": item.proposal_digest, "audit_valid": ledger.verify()}, indent=2))

if __name__ == "__main__": main()
