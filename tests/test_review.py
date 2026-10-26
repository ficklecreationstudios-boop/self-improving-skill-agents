from self_improving_agents.agents.review import review_output, propose_skill_update

def test_review_does_not_claim_semantic_quality():
    result = review_output("task", "answer")
    assert result.verdict == "generated"
    assert "semantic quality is not evaluated" in result.notes

def test_proposal_is_sealed():
    proposal = propose_skill_update("demo", "old", "new", "rationale")
    assert proposal.proposal_digest and proposal.sealed().proposal_digest == proposal.proposal_digest
