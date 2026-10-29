"""Container-side capability worker. Input and output are one bounded JSON object."""
import json
import sys

sys.path.insert(0, "/opt/package")
from self_improving_agents.capabilities import CapabilityRegistry

MAX_INPUT_BYTES = 65536
MAX_OUTPUT_BYTES = 524288

def main():
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("request exceeds input byte limit")
    request = json.loads(raw.decode("utf-8"))
    if not isinstance(request, dict) or set(request) != {"name", "arguments"}:
        raise ValueError("invalid request schema")

    registry = CapabilityRegistry("/workspace")
    result = registry.invoke(request["name"], request["arguments"])
    output = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(output) > MAX_OUTPUT_BYTES:
        output = json.dumps(
            {"ok": False, "error": "capability response exceeds output byte limit"},
            separators=(",", ":"),
        ).encode("utf-8")
    sys.stdout.buffer.write(output)
    sys.stdout.buffer.flush()

if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        # Never emit a traceback or arbitrary request contents to stdout.
        message = {"ok": False, "error": f"worker rejected request: {type(exc).__name__}"}
        try:
            sys.stdout.write(json.dumps(message, separators=(",", ":")))
            sys.stdout.flush()
        except BaseException:
            raise SystemExit(2)