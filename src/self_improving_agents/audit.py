"""Append-only JSONL hash-chain audit ledger."""
from __future__ import annotations
import json
from pathlib import Path
from hashlib import sha256
from datetime import datetime, timezone

class AuditLedger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
    def _events(self) -> list[dict]:
        if not self.path.exists(): return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    def append(self, event_type: str, payload: dict) -> dict:
        events = self._events()
        previous = events[-1]["event_hash"] if events else "0" * 64
        event = {"seq": len(events)+1, "timestamp": datetime.now(timezone.utc).isoformat(), "type": event_type, "payload": payload, "previous_hash": previous}
        canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        event["event_hash"] = sha256(canonical.encode("utf-8")).hexdigest()
        with self.path.open("a", encoding="utf-8") as stream: stream.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
        return event
    def verify(self) -> bool:
        previous = "0" * 64
        for index, event in enumerate(self._events(), start=1):
            if event.get("seq") != index or event.get("previous_hash") != previous: return False
            claimed = event.get("event_hash")
            base = {key: value for key, value in event.items() if key != "event_hash"}
            canonical = json.dumps(base, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            if sha256(canonical.encode("utf-8")).hexdigest() != claimed: return False
            previous = claimed
        return True
