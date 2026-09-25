import json
import math

import pytest

from src.event_digest.errors import make_json_safe


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(math.nan, "nan", id="nan"),
        pytest.param(math.inf, "inf", id="inf"),
        pytest.param(-math.inf, "-inf", id="negative-inf"),
    ],
)
def test_non_finite_floats_become_strings(value, expected):
    assert make_json_safe(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(0.0, id="zero-float"),
        pytest.param(-90.1, id="negative-float"),
        pytest.param(1e300, id="large-float"),
        pytest.param(91, id="int"),
        pytest.param(True, id="bool"),
        pytest.param(None, id="none"),
        pytest.param("nan", id="nan-string"),
        pytest.param("Infinity", id="infinity-string"),
        pytest.param("", id="empty-string"),
    ],
)
def test_other_scalars_are_unchanged(value):
    result = make_json_safe(value)

    assert result == value
    assert type(result) is type(value)


def test_nested_structures_are_sanitized_recursively():
    value = {
        "type": "finite_number",
        "loc": ["body", "events", 0, "location", "latitude"],
        "input": {"latitude": math.nan, "values": [1.5, math.inf, {"deep": -math.inf}]},
        "ctx": {"gt": 0.0, "limits": [math.nan, 90]},
    }

    assert make_json_safe(value) == {
        "type": "finite_number",
        "loc": ["body", "events", 0, "location", "latitude"],
        "input": {"latitude": "nan", "values": [1.5, "inf", {"deep": "-inf"}]},
        "ctx": {"gt": 0.0, "limits": ["nan", 90]},
    }


def test_result_is_strict_json():
    value = [{"input": math.nan}, {"input": [math.inf, -math.inf]}]

    # allow_nan=False raises for any remaining non-finite float.
    json.dumps(make_json_safe(value), allow_nan=False)


def test_json_safe_values_are_returned_unchanged():
    value = {"detail": [{"type": "missing", "loc": ["body", "events"], "msg": "Field required", "input": {}}]}

    assert make_json_safe(value) == value


def test_input_is_not_mutated():
    value = {"input": [math.nan]}

    make_json_safe(value)

    assert math.isnan(value["input"][0])
