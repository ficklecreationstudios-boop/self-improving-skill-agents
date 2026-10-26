from self_improving_agents.skills import discover_skills, select_skills, context_proxy

def test_discovers_and_selects_relevant_skill():
    skills = discover_skills("skills")
    assert {s.skill_id for s in skills} >= {"general", "software_engineering"}
    selected = select_skills("debug Python tests in a repository", "engineering", skills)
    assert selected and selected[0].skill_id == "software_engineering"

def test_context_proxy_is_explicitly_rough():
    assert context_proxy("one two three") == 3
