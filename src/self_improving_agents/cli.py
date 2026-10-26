"""Command-line entry point."""
import argparse, json
from .models import Task
from .orchestrator import run_task
from .skills import discover_skills, select_skills
from .audit import AuditLedger

def main() -> None:
    parser = argparse.ArgumentParser(prog="skill-agents")
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="Run a task using selected local skills")
    ask.add_argument("text"); ask.add_argument("--domain", default="general"); ask.add_argument("--skills", default="skills"); ask.add_argument("--audit", default="data/audit.jsonl")
    audit = sub.add_parser("verify-audit", help="Verify the hash-chain audit ledger"); audit.add_argument("--audit", default="data/audit.jsonl")
    bench = sub.add_parser("benchmark", help="Compare skill context proxy"); bench.add_argument("text"); bench.add_argument("--domain", default="general"); bench.add_argument("--skills", default="skills")
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

if __name__ == "__main__": main()
