"""Skill discovery and safe selective loading."""
from __future__ import annotations

from pathlib import Path
import re

from .models import Skill

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_SAFE_TAG = re.compile(r"^[a-zA-Z0-9_-]+$")
_ALLOWED_METADATA = {"id", "name", "domain", "tags"}
MAX_SKILL_BYTES = 1_000_000


def _parse_skill(path: Path, root: Path) -> Skill | None:
    # Resolve and validate containment before opening the file. In particular,
    # do not read bytes from an outside-root symlink and only then reject it.
    try:
        root_resolved = root.resolve(strict=True)
        path_resolved = path.resolve(strict=True)
        path_resolved.relative_to(root_resolved)
        if not path_resolved.is_file() or path_resolved.stat().st_size > MAX_SKILL_BYTES:
            return None
        text = path_resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError, RuntimeError, ValueError):
        return None

    if not text.startswith("---\n"):
        return None
    parts = text.split("---\n", 2)
    if len(parts) != 3:
        return None
    _, front, body = parts

    metadata: dict[str, str] = {}
    for line in front.splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            return None
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if key not in _ALLOWED_METADATA or key in metadata or not value:
            return None
        metadata[key] = value

    skill_id = metadata.get("id", path_resolved.parent.name)
    if not _SAFE_ID.fullmatch(skill_id):
        return None

    tags_raw = metadata.get("tags", "[]").strip()
    if not (tags_raw.startswith("[") and tags_raw.endswith("]")):
        return None
    tags_text = tags_raw[1:-1].strip()
    if tags_text:
        tags = tuple(tag.strip().strip("\"'") for tag in tags_text.split(","))
        if any(not tag or not _SAFE_TAG.fullmatch(tag) for tag in tags):
            return None
    else:
        tags = ()

    return Skill(
        skill_id=skill_id,
        name=metadata.get("name", skill_id),
        domain=metadata.get("domain", "general"),
        tags=tags,
        path=str(path_resolved),
        content=body.strip(),
    )


def discover_skills(root: str | Path) -> list[Skill]:
    base = Path(root).resolve()
    if not base.exists():
        return []
    found = []
    for path in sorted(base.rglob("SKILL.md")):
        item = _parse_skill(path, base)
        if item:
            found.append(item)
    return found


def select_skills(task_text: str, domain: str, skills: list[Skill], limit: int = 3) -> list[Skill]:
    words = set(re.findall(r"[a-zA-Z0-9_-]+", task_text.lower()))
    ranked = []
    for skill in skills:
        score = 3 if skill.domain.lower() == domain.lower() else 0
        score += sum(1 for tag in skill.tags if tag.lower() in words)
        score += sum(1 for word in words if len(word) > 3 and word in skill.name.lower())
        if score > 0 or skill.domain == "general":
            ranked.append((score, skill.skill_id, skill))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in ranked[:max(0, limit)]]


def context_proxy(text: str) -> int:
    """Whitespace-piece proxy, not a model tokenizer."""
    return len(text.split())
