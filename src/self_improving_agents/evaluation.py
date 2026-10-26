"""Deterministic routing evaluation for reviewed JSONL cases.

This reports retrieval-label agreement only; it does not measure generated-answer quality.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any
from .skills import discover_skills, select_skills


def evaluate_routing(cases: list[dict[str, Any]], skills: list, top_k: int = 3) -> dict[str, Any]:
    if top_k < 1:
        raise ValueError("top_k must be >= 1")
    if not cases:
        raise ValueError("at least one evaluation case is required")
    results = []
    top1_hits = 0
    topk_hits = 0
    for index, case in enumerate(cases, start=1):
        task = case.get("task")
        domain = case.get("domain", "general")
        expected = case.get("expected_skill_id")
        if not isinstance(task, str) or not task.strip():
            raise ValueError(f"case {index}: 'task' must be a non-empty string")
        if not isinstance(domain, str) or not domain.strip():
            raise ValueError(f"case {index}: 'domain' must be a non-empty string")
        if not isinstance(expected, str) or not expected.strip():
            raise ValueError(f"case {index}: 'expected_skill_id' must be a non-empty string")
        selected = select_skills(task, domain, skills, limit=top_k)
        ranked = [skill.skill_id for skill in selected]
        hit_top1 = bool(ranked) and ranked[0] == expected
        hit_topk = expected in ranked
        top1_hits += int(hit_top1)
        topk_hits += int(hit_topk)
        results.append({
            "case_id": case.get("case_id", str(index)),
            "domain": domain,
            "expected_skill_id": expected,
            "selected_skill_ids": ranked,
            "top1_correct": hit_top1,
            "topk_correct": hit_topk,
        })
    count = len(cases)
    return {
        "metric_scope": "routing-label agreement only; not answer quality or safety",
        "case_count": count,
        "top_k": top_k,
        "top1_accuracy": round(top1_hits / count, 4),
        "topk_recall": round(topk_hits / count, 4),
        "cases": results,
    }


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    cases = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_number}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"Line {line_number} must contain a JSON object")
        cases.append(item)
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="eval/routing_smoke.jsonl")
    parser.add_argument("--skills", default="skills")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = evaluate_routing(load_jsonl(args.cases), discover_skills(args.skills), args.top_k)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
