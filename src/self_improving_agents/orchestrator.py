"""End-to-end task flow."""
from pathlib import Path
from .models import Task
from .skills import discover_skills, select_skills
from .ollama import OllamaAdapter
from .agents.specialists import execute_task
from .audit import AuditLedger

def run_task(task: Task, skill_root: str | Path = "skills", audit_path: str | Path = "data/audit.jsonl", adapter: OllamaAdapter | None = None):
    skills = discover_skills(skill_root)
    selected = select_skills(task.text, task.domain, skills)
    ledger = AuditLedger(audit_path)
    result = execute_task(task, selected, adapter or OllamaAdapter())
    ledger.append("task_completed", {"task_digest": result.task_digest, "output_digest": result.output_digest, "skills": result.skill_ids, "review_verdict": result.review.verdict, "review_notes": result.review.notes})
    return result
