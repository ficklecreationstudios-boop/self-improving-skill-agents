# Routing evaluation

Run from the repository root:

```powershell
python -m self_improving_agents.evaluation --cases eval/routing_smoke.jsonl --skills skills
```

The bundled six-case fixture is a **smoke test**, not an independent holdout and not evidence of general routing accuracy. It only checks agreement with these manually specified expected skill labels. For a meaningful quality gate, create a separately curated, versioned dataset with positive and negative examples, freeze it before tuning, record a baseline, and report uncertainty and per-domain results. Do not tune on the final holdout and then present it as independent evaluation.

Metrics:
- `top1_accuracy`: fraction where the first selected skill matches the expected label.
- `topk_recall`: fraction where the expected label appears anywhere in the first `k` selected skills.
- Neither metric measures generated-answer correctness, safety, calibration, or whether the task itself should have been refused.
