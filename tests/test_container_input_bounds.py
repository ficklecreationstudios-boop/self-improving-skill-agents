import json
import math

import pytest

from self_improving_agents.container_capabilities import (
    MAX_REQUEST_BYTES,
    MAX_TIMEOUT_SECONDS,
    ContainerCapabilityRegistry,
    _bounded_json_size,
)


def test_json_size_estimate_bounds_actual_utf8_json_size():
    payload = {
        "plain": "hello",
        "unicode": "caf? ??",
        "escaped": 'quotes " slash \\\\ newline\n',
        "items": [None, True, False, -123, 1.25],
    }

    estimated = _bounded_json_size(payload)
    actual = len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )

    assert actual <= estimated <= MAX_REQUEST_BYTES


def test_json_size_rejects_oversized_string_before_serialization():
    with pytest.raises(ValueError):
        _bounded_json_size({"text": "x" * (MAX_REQUEST_BYTES + 1)})


def test_json_size_rejects_excessive_nesting():
    value = None
    for _ in range(40):
        value = [value]

    with pytest.raises(ValueError, match="nesting-depth"):
        _bounded_json_size(value)


def test_json_size_rejects_excessive_item_count():
    with pytest.raises(ValueError, match="item-count"):
        _bounded_json_size(list(range(100)), max_nodes=20)


def test_json_size_rejects_cycles():
    value = []
    value.append(value)

    with pytest.raises(ValueError, match="Cyclic"):
        _bounded_json_size(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_json_size_rejects_non_finite_numbers(value):
    with pytest.raises(ValueError):
        _bounded_json_size({"value": value})


def test_json_size_rejects_non_json_values():
    with pytest.raises(ValueError, match="JSON-compatible"):
        _bounded_json_size({"value": {1, 2, 3}})


@pytest.mark.parametrize(
    "timeout",
    [
        0,
        -1,
        True,
        float("nan"),
        float("inf"),
        float("-inf"),
        MAX_TIMEOUT_SECONDS + 1,
        10**100,
    ],
)
def test_registry_rejects_invalid_timeout_values(tmp_path, timeout):
    with pytest.raises(ValueError):
        ContainerCapabilityRegistry(tmp_path, timeout_seconds=timeout)


def test_registry_accepts_timeout_at_upper_bound(tmp_path):
    registry = ContainerCapabilityRegistry(
        tmp_path, timeout_seconds=MAX_TIMEOUT_SECONDS
    )

    assert registry.timeout_seconds == MAX_TIMEOUT_SECONDS
