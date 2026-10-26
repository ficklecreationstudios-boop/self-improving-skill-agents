"""Context-size proxy; not a tokenizer benchmark."""
from .skills import context_proxy
from .models import Skill

def compare_context(task: str, skills: list[Skill], selected: list[Skill]) -> dict[str, int | float]:
    baseline = context_proxy(task + "\n" + "\n".join(s.content for s in skills))
    candidate = context_proxy(task + "\n" + "\n".join(s.content for s in selected))
    reduction = 0.0 if baseline == 0 else 100.0 * (baseline - candidate) / baseline
    return {"all_skill_pieces_proxy": baseline, "selected_skill_pieces_proxy": candidate, "reduction_percent_proxy": round(reduction, 2)}
