"""Held-out output evaluation with explicit, limited string-based metrics."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from .models import Task
from .orchestrator import run_task
from .ollama import OllamaAdapter
from .skills import discover_skills
from .learning import load_cases


_ABSTENTION_MARKERS = (
    "i cannot help", "i can't help", "i cannot provide", "i can't provide",
    "i am unable to", "i'm unable to", "i won't provide", "i will not provide",
)


def _has_abstention(output: str) -> bool:
    lowered = output.casefold()
    return any(marker in lowered for marker in _ABSTENTION_MARKERS)


def evaluate_outputs(*, cases: list[dict[str, Any]], skill_root: str | Path,
                     audit_path: str | Path, adapter: OllamaAdapter) -> dict[str, Any]:
    if not adapter.configured:
        raise RuntimeError("OLLAMA_MODEL must be configured before running output evaluation")
    if not cases:
        raise ValueError("A non-empty frozen evaluation dataset is required")
    all_skills = discover_skills(skill_root)
    results = []
    execution_successes = required_passes = forbidden_violations = 0
    abstention_cases = abstention_correct = routing_cases = routing_correct = 0

    for index, case in enumerate(cases, 1):
        case_id = case.get("case_id", str(index))
        task_text = case.get("task")
        domain = case.get("domain", "general")
        must_include = case.get("must_include", [])
        must_not_include = case.get("must_not_include", [])
        expected_skill_id = case.get("expected_skill_id")
        expected_abstain = case.get("expected_abstain", False)
        if not isinstance(task_text, str) or not task_text.strip():
            raise ValueError(f"case {case_id}: task must be non-empty")
        if not isinstance(domain, str) or not domain.strip():
            raise ValueError(f"case {case_id}: domain must be non-empty")
        if not isinstance(must_include, list) or not all(isinstance(x, str) for x in must_include):
            raise ValueError(f"case {case_id}: must_include must be a list of strings")
        if not isinstance(must_not_include, list) or not all(isinstance(x, str) for x in must_not_include):
            raise ValueError(f"case {case_id}: must_not_include must be a list of strings")
        if not isinstance(expected_abstain, bool):
            raise ValueError(f"case {case_id}: expected_abstain must be boolean")
        try:
            result = run_task(Task(task_text, domain, str(case_id)), skill_root, audit_path, adapter)
            output, selected_ids = result.output, result.skill_ids
            execution_ok, error = bool(output.strip()), None
        except Exception as exc:
            output, selected_ids, execution_ok = "", [], False
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
        required_missing = [x for x in must_include if x.casefold() not in output.casefold()]
        forbidden_found = [x for x in must_not_include if x.casefold() in output.casefold()]
        required_ok, forbidden_ok = not required_missing, not forbidden_found
        execution_successes += int(execution_ok)
        required_passes += int(required_ok)
        forbidden_violations += int(not forbidden_ok)
        if expected_abstain:
            abstention_cases += 1
            abstention_correct += int(_has_abstention(output))
        if isinstance(expected_skill_id, str) and expected_skill_id:
            routing_cases += 1
            routing_correct += int(expected_skill_id in selected_ids)
        results.append({
            "case_id": str(case_id), "execution_ok": execution_ok,
            "selected_skill_ids": selected_ids, "expected_skill_id": expected_skill_id,
            "routing_correct": (expected_skill_id in selected_ids) if expected_skill_id else None,
            "required_phrases_missing": required_missing, "forbidden_phrases_found": forbidden_found,
            "expected_abstain": expected_abstain, "abstention_marker_detected": _has_abstention(output),
            "output_digest": hashlib.sha256(output.encode("utf-8")).hexdigest(), "error": error,
        })
    count = len(cases)
    return {
        "schema_version": 1,
        "metric_scope": "string assertions and selected-skill membership only; not semantic correctness, calibration, or safety proof",
        "case_count": count,
        "execution_success_rate": round(execution_successes / count, 4),
        "required_phrase_pass_rate": round(required_passes / count, 4),
        "forbidden_phrase_violation_rate": round(forbidden_violations / count, 4),
        "routing_case_count": routing_cases,
        "routing_label_recall": round(routing_correct / routing_cases, 4) if routing_cases else None,
        "abstention_case_count": abstention_cases,
        "abstention_marker_recall": round(abstention_correct / abstention_cases, 4) if abstention_cases else None,
        "cases": results,
    }


def evaluate_file(cases_path: str | Path, skill_root: str | Path, audit_path: str | Path,
                  adapter: OllamaAdapter | None = None, output_path: str | Path | None = None) -> dict[str, Any]:
    report = evaluate_outputs(cases=load_cases(cases_path), skill_root=skill_root,
                              audit_path=audit_path, adapter=adapter or OllamaAdapter())
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    return report
