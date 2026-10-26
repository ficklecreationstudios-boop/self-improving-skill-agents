"""Skill discovery and safe selective loading."""
from __future__ import annotations
from pathlib import Path
import re
from .models import Skill
_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")

def _parse_skill(path: Path, root: Path) -> Skill | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"): return None
    try: _, front, body = text.split("---\n", 2)
    except ValueError: return None
    metadata = {}
    for line in front.splitlines():
        if ":" in line:
            key, value = line.split(":", 1); metadata[key.strip()] = value.strip()
    skill_id = metadata.get("id", path.parent.name)
    if not _SAFE_ID.fullmatch(skill_id): return None
    tags_raw = metadata.get("tags", "[]").strip().strip("[]")
    tags = tuple(tag.strip().strip("\"'") for tag in tags_raw.split(",") if tag.strip())
    root_resolved, path_resolved = root.resolve(), path.resolve()
    if root_resolved not in path_resolved.parents: return None
    return Skill(skill_id, metadata.get("name", skill_id), metadata.get("domain", "general"), tags, str(path_resolved), body.strip())

def discover_skills(root: str | Path) -> list[Skill]:
    base = Path(root).resolve()
    if not base.exists(): return []
    found = []
    for path in sorted(base.rglob("SKILL.md")):
        item = _parse_skill(path, base)
        if item: found.append(item)
    return found

def select_skills(task_text: str, domain: str, skills: list[Skill], limit: int = 3) -> list[Skill]:
    words = set(re.findall(r"[a-zA-Z0-9_-]+", task_text.lower()))
    ranked = []
    for skill in skills:
        score = 3 if skill.domain.lower() == domain.lower() else 0
        score += sum(1 for tag in skill.tags if tag.lower() in words)
        score += sum(1 for word in words if len(word) > 3 and word in skill.name.lower())
        if score > 0 or skill.domain == "general": ranked.append((score, skill.skill_id, skill))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in ranked[:max(0, limit)]]

def context_proxy(text: str) -> int:
    """Whitespace-piece proxy, not a model tokenizer."""
    return len(text.split())
