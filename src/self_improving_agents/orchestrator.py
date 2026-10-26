"""End-to-end task flow with explicit non-execution when inference is unavailable."""
from pathlib import Path
from .models import Task, digest_text
from .skills import discover_skills, select_skills
from .ollama import OllamaAdapter
from .agents.specialists import execute_task
from .audit import AuditLedger


class ModelNotConfiguredError(RuntimeError):
    """Raised when no actual model inference can be performed."""


def run_task(task: Task, skill_root: str | Path = "skills",
             audit_path: str | Path = "data/audit.jsonl",
             adapter: OllamaAdapter | None = None):
    skills = discover_skills(skill_root)
    selected = select_skills(task.text, task.domain, skills)
    ledger = AuditLedger(audit_path)
    model = adapter or OllamaAdapter()
    if not model.configured:
        ledger.append("task_not_executed", {
            "task_id": task.task_id,
            "task_digest": digest_text(task.text),
            "skills": [skill.skill_id for skill in selected],
            "reason": "ollama_model_not_configured",
        })
        raise ModelNotConfiguredError(
            "No Ollama model configured. Set OLLAMA_MODEL; no model inference was performed."
        )
    try:
        result = execute_task(task, selected, model)
    except Exception as exc:
        ledger.append("task_execution_failed", {
            "task_id": task.task_id,
            "task_digest": digest_text(task.text),
            "skills": [skill.skill_id for skill in selected],
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        })
        raise
    ledger.append("task_completed", {
        "task_id": task.task_id,
        "task_digest": result.task_digest,
        "output_digest": result.output_digest,
        "skills": result.skill_ids,
        "review_verdict": result.review.verdict,
        "review_notes": result.review.notes,
    })
    return result
