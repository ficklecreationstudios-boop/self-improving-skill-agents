"""Held-out output evaluation with pre-registered thresholds and limited string metrics."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any
from .models import Task
from .orchestrator import run_task
from .ollama import OllamaAdapter
from .skills import discover_skills
from .audit import AuditLedger

_ABSTENTION_MARKERS = (
    "i cannot help", "i can't help", "i cannot provide", "i can't provide",
    "i am unable to", "i'm unable to", "i won't provide", "i will not provide",
)
_ALLOWED_THRESHOLDS = {
    "minimum_execution_success_rate", "minimum_required_phrase_pass_rate",
    "maximum_forbidden_phrase_violation_rate", "minimum_routing_label_recall",
    "minimum_abstention_marker_recall",
}


def _has_abstention(output: str) -> bool:
    lowered = output.casefold()
    return any(marker in lowered for marker in _ABSTENTION_MARKERS)


def _parse_cases(raw: bytes) -> list[dict[str, Any]]:
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Evaluation case file must be UTF-8") from exc
    cases = []
    for line_number, line in enumerate(content.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid evaluation JSON on line {line_number}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"Evaluation line {line_number} must contain a JSON object")
        cases.append(item)
    if not cases:
        raise ValueError("A non-empty frozen evaluation dataset is required")
    return cases


def _skill_corpus_digest(skill_root: str | Path) -> str:
    root = Path(skill_root).resolve()
    records = []
    for skill in discover_skills(root):
        path = Path(skill.path).resolve(strict=True)
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError("Discovered skill escapes configured skill root") from exc
        records.append({"path": relative, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    records.sort(key=lambda row: row["path"])
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_thresholds(value: Any) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise ValueError("A non-empty threshold object must be preregistered before evaluation")
    unknown = set(value) - _ALLOWED_THRESHOLDS
    if unknown:
        raise ValueError(f"Unknown evaluation thresholds: {sorted(unknown)}")
    normalized = {}
    for key, number in value.items():
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not 0 <= number <= 1:
            raise ValueError(f"Threshold {key} must be a number between 0 and 1")
        normalized[key] = float(number)
    return normalized


def evaluate_outputs(*, cases: list[dict[str, Any]], skill_root: str | Path,
                     audit_path: str | Path, adapter: OllamaAdapter) -> dict[str, Any]:
    if not adapter.configured:
        raise RuntimeError("OLLAMA_MODEL must be configured before running output evaluation")
    if not cases:
        raise ValueError("A non-empty frozen evaluation dataset is required")
    results = []
    execution_successes = 0
    required_case_count = required_passes = 0
    forbidden_case_count = forbidden_violations = 0
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
        execution_successes += int(execution_ok)
        if must_include:
            required_case_count += 1
            required_passes += int(not required_missing)
        if must_not_include:
            forbidden_case_count += 1
            forbidden_violations += int(bool(forbidden_found))
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
        "required_phrase_case_count": required_case_count,
        "required_phrase_pass_rate": round(required_passes / required_case_count, 4) if required_case_count else None,
        "forbidden_phrase_case_count": forbidden_case_count,
        "forbidden_phrase_violation_rate": round(forbidden_violations / forbidden_case_count, 4) if forbidden_case_count else None,
        "routing_case_count": routing_cases,
        "routing_label_recall": round(routing_correct / routing_cases, 4) if routing_cases else None,
        "abstention_case_count": abstention_cases,
        "abstention_marker_recall": round(abstention_correct / abstention_cases, 4) if abstention_cases else None,
        "cases": results,
    }


def _evaluate_thresholds(report: dict[str, Any], thresholds: dict[str, float]) -> dict[str, Any]:
    mapping = {
        "minimum_execution_success_rate": ("execution_success_rate", "min"),
        "minimum_required_phrase_pass_rate": ("required_phrase_pass_rate", "min"),
        "maximum_forbidden_phrase_violation_rate": ("forbidden_phrase_violation_rate", "max"),
        "minimum_routing_label_recall": ("routing_label_recall", "min"),
        "minimum_abstention_marker_recall": ("abstention_marker_recall", "min"),
    }
    checks = {}
    for name, threshold in thresholds.items():
        metric, direction = mapping[name]
        actual = report.get(metric)
        if actual is None:
            passed, reason = False, "metric has no eligible cases"
        else:
            passed = actual >= threshold if direction == "min" else actual <= threshold
            reason = None if passed else f"{metric}={actual} does not meet {name}={threshold}"
        checks[name] = {"metric": metric, "threshold": threshold, "actual": actual,
                        "passed": passed, "reason": reason}
    return {"passed": all(item["passed"] for item in checks.values()), "checks": checks}


def evaluate_file(cases_path: str | Path, skill_root: str | Path, audit_path: str | Path,
                  adapter: OllamaAdapter | None = None, output_path: str | Path | None = None,
                  thresholds_path: str | Path | None = None) -> dict[str, Any]:
    if thresholds_path is None:
        raise ValueError("A threshold file must be provided and preregistered before evaluation")
    case_bytes = Path(cases_path).read_bytes()
    threshold_bytes = Path(thresholds_path).read_bytes()
    cases = _parse_cases(case_bytes)
    thresholds = validate_thresholds(json.loads(threshold_bytes.decode("utf-8")))
    case_digest = hashlib.sha256(case_bytes).hexdigest()
    threshold_digest = hashlib.sha256(threshold_bytes).hexdigest()
    skills_digest = _skill_corpus_digest(skill_root)
    ledger = AuditLedger(audit_path)
    ledger.append("quality_evaluation_preregistered", {
        "cases_digest": case_digest, "thresholds_digest": threshold_digest,
        "skills_digest": skills_digest, "thresholds": thresholds,
    })
    try:
        report = evaluate_outputs(cases=cases, skill_root=skill_root,
                                  audit_path=audit_path, adapter=adapter or OllamaAdapter())
        if _skill_corpus_digest(skill_root) != skills_digest:
            raise RuntimeError("Skill corpus changed during evaluation; report is invalid")
        report["preregistration"] = {
            "cases_digest": case_digest, "thresholds_digest": threshold_digest,
            "skills_digest": skills_digest, "thresholds": thresholds,
            "recorded_before_model_run": True,
        }
        report["gate"] = _evaluate_thresholds(report, thresholds)
        ledger.append("quality_evaluation_completed", {
            "cases_digest": case_digest, "thresholds_digest": threshold_digest,
            "skills_digest": skills_digest, "gate_passed": report["gate"]["passed"],
            "metrics": {key: value for key, value in report.items()
                        if key.endswith("_rate") or key.endswith("_recall") or key.endswith("_count")},
        })
    except Exception as exc:
        ledger.append("quality_evaluation_failed", {
            "cases_digest": case_digest, "thresholds_digest": threshold_digest,
            "skills_digest": skills_digest, "error_type": type(exc).__name__, "error": str(exc)[:500],
        })
        raise
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    return report
