from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.config import schema
from src.config.parser import parse_config
from src.config.schema import EventScoutConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]

VALID_CONFIG_YAML = """
center:
  name: Joutsa
  latitude: 61.742667
  longitude: 26.112972

radius_km: 100

lookahead_weeks: 3

categories:
  - concert
  - live_music
  - stand_up
  - comedy
  - cultural
"""


def valid_config_dict() -> dict:
    return yaml.safe_load(VALID_CONFIG_YAML)


def error_locations(error: ValidationError) -> set[tuple]:
    return {tuple(detail["loc"]) for detail in error.errors()}


# --- Valid configuration -----------------------------------------------------


def test_parse_config_returns_validated_model():
    config = parse_config(VALID_CONFIG_YAML)

    assert isinstance(config, EventScoutConfig)
    assert config.center.name == "Joutsa"
    assert config.center.latitude == 61.742667
    assert config.center.longitude == 26.112972
    assert config.radius_km == 100
    assert config.lookahead_weeks == 3
    assert config.categories == [
        "concert",
        "live_music",
        "stand_up",
        "comedy",
        "cultural",
    ]


def test_parse_config_accepts_project_config_file():
    yaml_text = (PROJECT_ROOT / "config" / "events.yaml").read_text(encoding="utf-8")

    config = parse_config(yaml_text)

    assert isinstance(config, EventScoutConfig)
    assert config.categories


def test_parse_config_coerces_integer_coordinates_and_radius_to_float():
    data = valid_config_dict()
    data["center"]["latitude"] = 61
    data["radius_km"] = 50

    config = parse_config(yaml.safe_dump(data))

    assert isinstance(config.center.latitude, float)
    assert isinstance(config.radius_km, float)


def test_model_dump_round_trips_through_parser():
    config = parse_config(VALID_CONFIG_YAML)

    reparsed = parse_config(yaml.safe_dump(config.model_dump()))

    assert reparsed == config


# --- Non-mapping / malformed YAML --------------------------------------------


@pytest.mark.parametrize(
    "yaml_text",
    [
        pytest.param("", id="empty"),
        pytest.param("# only a comment\n", id="comment-only"),
        pytest.param("- concert\n- comedy\n", id="list"),
        pytest.param("just a string", id="scalar"),
        pytest.param("42", id="number"),
    ],
)
def test_parse_config_rejects_non_mapping_yaml(yaml_text):
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        parse_config(yaml_text)


def test_parse_config_raises_yaml_error_for_invalid_syntax():
    with pytest.raises(yaml.YAMLError):
        parse_config("center: [unclosed\n")


# --- Missing values ----------------------------------------------------------


@pytest.mark.parametrize(
    "missing_field",
    ["center", "radius_km", "lookahead_weeks", "categories"],
)
def test_parse_config_requires_top_level_field(missing_field):
    data = valid_config_dict()
    del data[missing_field]

    with pytest.raises(ValidationError) as exc_info:
        parse_config(yaml.safe_dump(data))

    assert (missing_field,) in error_locations(exc_info.value)


@pytest.mark.parametrize("missing_field", ["name", "latitude", "longitude"])
def test_parse_config_requires_center_field(missing_field):
    data = valid_config_dict()
    del data["center"][missing_field]

    with pytest.raises(ValidationError) as exc_info:
        parse_config(yaml.safe_dump(data))

    assert ("center", missing_field) in error_locations(exc_info.value)


def test_parse_config_reports_all_missing_fields_at_once():
    with pytest.raises(ValidationError) as exc_info:
        parse_config("unrelated_key: value\n")

    assert error_locations(exc_info.value) == {
        ("center",),
        ("radius_km",),
        ("lookahead_weeks",),
        ("categories",),
    }


# --- Invalid values ----------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("radius_km", 0, id="radius-zero"),
        pytest.param("radius_km", -10, id="radius-negative"),
        pytest.param("lookahead_weeks", 0, id="weeks-zero"),
        pytest.param("lookahead_weeks", -1, id="weeks-negative"),
    ],
)
def test_parse_config_rejects_non_positive_numbers(field, value):
    data = valid_config_dict()
    data[field] = value

    with pytest.raises(ValidationError) as exc_info:
        parse_config(yaml.safe_dump(data))

    assert (field,) in error_locations(exc_info.value)


@pytest.mark.parametrize("yaml_value", [".inf", "-.inf", ".nan"])
def test_parse_config_rejects_non_finite_radius(yaml_value):
    yaml_text = VALID_CONFIG_YAML.replace("radius_km: 100", f"radius_km: {yaml_value}")

    with pytest.raises(ValidationError) as exc_info:
        parse_config(yaml_text)

    [error] = exc_info.value.errors()
    assert (error["type"], error["loc"]) == ("finite_number", ("radius_km",))


@pytest.mark.parametrize("radius_km", [0.001, 100, 1e300])
def test_parse_config_accepts_finite_positive_radius(radius_km):
    data = valid_config_dict()
    data["radius_km"] = radius_km

    assert parse_config(yaml.safe_dump(data)).radius_km == radius_km


@pytest.mark.parametrize("yaml_value", [".inf", ".nan"])
def test_parse_config_non_finite_lookahead_weeks_is_unchanged(yaml_value):
    # lookahead_weeks is an int; non-finite values were already rejected.
    yaml_text = VALID_CONFIG_YAML.replace("lookahead_weeks: 3", f"lookahead_weeks: {yaml_value}")

    with pytest.raises(ValidationError) as exc_info:
        parse_config(yaml_text)

    assert exc_info.value.errors()[0]["type"] == "finite_number"


def test_parse_config_rejects_lookahead_weeks_beyond_representable_dates():
    data = valid_config_dict()
    data["lookahead_weeks"] = 10**9

    with pytest.raises(ValidationError) as exc_info:
        parse_config(yaml.safe_dump(data))

    [error] = exc_info.value.errors()
    assert error["type"] == "less_than_equal"
    assert error["loc"] == ("lookahead_weeks",)


def test_parse_config_lookahead_limit_uses_shared_date_helper(monkeypatch):
    monkeypatch.setattr(schema, "max_lookahead_weeks", lambda: 4)
    data = valid_config_dict()

    data["lookahead_weeks"] = 4
    assert parse_config(yaml.safe_dump(data)).lookahead_weeks == 4

    data["lookahead_weeks"] = 5
    with pytest.raises(ValidationError) as exc_info:
        parse_config(yaml.safe_dump(data))
    assert exc_info.value.errors()[0]["ctx"] == {"le": 4}


def test_parse_config_rejects_empty_categories():
    data = valid_config_dict()
    data["categories"] = []

    with pytest.raises(ValidationError) as exc_info:
        parse_config(yaml.safe_dump(data))

    assert ("categories",) in error_locations(exc_info.value)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        pytest.param(("radius_km",), "far away", id="radius-not-number"),
        pytest.param(("lookahead_weeks",), 2.5, id="weeks-fractional"),
        pytest.param(("lookahead_weeks",), "three", id="weeks-not-number"),
        pytest.param(("categories",), "concert", id="categories-not-list"),
        pytest.param(("center",), "Joutsa", id="center-not-mapping"),
        pytest.param(("center", "latitude"), "north", id="latitude-not-number"),
    ],
)
def test_parse_config_rejects_wrong_types(path, value):
    data = valid_config_dict()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValidationError) as exc_info:
        parse_config(yaml.safe_dump(data))

    locations = error_locations(exc_info.value)
    assert any(location[: len(path)] == path for location in locations)


# --- Center coordinates ------------------------------------------------------


def config_with_center(**center) -> str:
    data = valid_config_dict()
    data["center"].update(center)
    return yaml.safe_dump(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("latitude", -90, id="latitude-min"),
        pytest.param("latitude", 90, id="latitude-max"),
        pytest.param("latitude", 0, id="latitude-zero"),
        pytest.param("longitude", -180, id="longitude-min"),
        pytest.param("longitude", 180, id="longitude-max"),
        pytest.param("longitude", 0, id="longitude-zero"),
    ],
)
def test_parse_config_accepts_center_coordinates_within_bounds(field, value):
    config = parse_config(config_with_center(**{field: value}))

    assert getattr(config.center, field) == value


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        pytest.param("latitude", -90.1, "greater_than_equal", id="latitude-below-min"),
        pytest.param("latitude", 90.1, "less_than_equal", id="latitude-above-max"),
        pytest.param("longitude", -180.1, "greater_than_equal", id="longitude-below-min"),
        pytest.param("longitude", 180.1, "less_than_equal", id="longitude-above-max"),
        pytest.param("latitude", float("inf"), "finite_number", id="latitude-inf"),
        pytest.param("latitude", float("-inf"), "finite_number", id="latitude-negative-inf"),
        pytest.param("latitude", float("nan"), "finite_number", id="latitude-nan"),
        pytest.param("longitude", float("inf"), "finite_number", id="longitude-inf"),
        pytest.param("longitude", float("-inf"), "finite_number", id="longitude-negative-inf"),
        pytest.param("longitude", float("nan"), "finite_number", id="longitude-nan"),
    ],
)
def test_parse_config_rejects_invalid_center_coordinates(field, value, error_type):
    with pytest.raises(ValidationError) as exc_info:
        parse_config(config_with_center(**{field: value}))

    [error] = exc_info.value.errors()
    assert (error["type"], error["loc"]) == (error_type, ("center", field))


# --- Current lenient behavior ------------------------------------------------
# These tests document existing behavior so that any future tightening of the
# schema (e.g. forbidding unknown keys) is a deliberate, visible change.


def test_parse_config_ignores_unknown_keys():
    data = valid_config_dict()
    data["id"] = "w9spsn"

    config = parse_config(yaml.safe_dump(data))

    assert "id" not in config.model_dump()
