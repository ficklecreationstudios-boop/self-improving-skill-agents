"""Minimal transparent review and proposal generation."""
from ..models import Review, Proposal, digest_text

def review_output(task_text: str, output: str) -> Review:
    verdict = "needs_review" if not output.strip() else "generated"
    notes = "Empty output requires attention." if not output.strip() else "Basic non-empty-output check only; semantic quality is not evaluated."
    return Review(digest_text(task_text), digest_text(output), verdict, notes)

def propose_skill_update(skill_id: str, current_content: str, proposed_content: str, rationale: str) -> Proposal:
    return Proposal(skill_id, digest_text(current_content), proposed_content, rationale).sealed()
