from concurrent.futures import ThreadPoolExecutor
import json
from self_improving_agents.agents.review import propose_skill_update
from self_improving_agents.audit import AuditLedger
from self_improving_agents.governance.approval import Governance, GovernanceError

KEY = b"test-only-approval-key-material-32-bytes-minimum!!"


def test_concurrent_applications_of_same_proposal_allow_only_one_update(tmp_path):
    root = tmp_path / "skills"; folder = root / "demo"; folder.mkdir(parents=True)
    old = "---\nid: demo\n---\nold"
    new = "---\nid: demo\n---\nnew"
    target = folder / "SKILL.md"; target.write_text(old, encoding="utf-8")
    audit = AuditLedger(tmp_path / "audit.jsonl")
    governance = Governance(root, tmp_path / "archive", audit, approval_key=KEY)
    proposal = propose_skill_update("demo", old, new, "reviewed concurrent proposal")
    approval = governance.issue_approval(proposal, "reviewer", True, "approved once")

    def apply_once():
        try:
            governance.apply(proposal, approval)
            return "applied"
        except GovernanceError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [future.result(timeout=30) for future in
                    [pool.submit(apply_once), pool.submit(apply_once)]]
    assert outcomes.count("applied") == 1
    assert sum("Stale proposal" in value for value in outcomes) == 1
    assert target.read_text(encoding="utf-8") == new
    events = [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]
    assert sum(event["type"] == "skill_update_applied" for event in events) == 1
    assert audit.verify()
