"""Tests for the FastAPI boundary in src/event_digest/api.py.

These tests document the current HTTP contract: happy paths for every
endpoint, the request validation the Pydantic models already enforce, and
(in the known-issues section) malformed input that currently reaches the
domain functions.
"""

import json
from datetime import date
from functools import partial
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from src.event_digest import api, search_context
from src.event_digest.dates import calculate_date_range

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLEVENTS_PAGE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "allevents-jyvaskyla-music.html"

# Friday; the search period is therefore Monday 2026-09-28 to Sunday 2026-10-18.
FIXED_TODAY = date(2026, 9, 25)
START_DATE = "2026-09-28"
END_DATE = "2026-10-18"

CONFIG_YAML = """
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

EXPECTED_CONFIG = {
    "center": {"name": "Joutsa", "latitude": 61.742667, "longitude": 26.112972},
    "radius_km": 100.0,
    "lookahead_weeks": 3,
    "categories": ["concert", "live_music", "stand_up", "comedy", "cultural"],
}

JOUTSA = {"center_lat": 61.742667, "center_lon": 26.112972}

ENDPOINTS = {
    ("GET", "/health"),
    ("POST", "/config/parse"),
    ("POST", "/dates/calculate"),
    ("POST", "/search/context"),
    ("POST", "/search/queries"),
    ("POST", "/events/extract"),
    ("POST", "/events/location"),
    ("POST", "/events/filter-radius"),
    ("POST", "/events/filter-date"),
    ("POST", "/events/deduplicate"),
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    # Unhandled exceptions become HTTP 500 responses, as in production,
    # instead of being re-raised into the test.
    return TestClient(api.app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    """Pin 'today' for endpoints that calculate the search date range."""

    pinned = partial(calculate_date_range, today=FIXED_TODAY)
    monkeypatch.setattr(api, "calculate_date_range", pinned)
    monkeypatch.setattr(search_context, "calculate_date_range", pinned)


def jsonld_html(*events: dict) -> str:
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(event)}</script>'
        for event in events
    )
    return f"<html><head>{scripts}</head><body></body></html>"


def event_at(name: str, latitude, longitude, **fields) -> dict:
    return {"name": name, "location": {"latitude": latitude, "longitude": longitude}, **fields}


def validation_errors(response) -> set[tuple[str, tuple]]:
    return {(error["type"], tuple(error["loc"])) for error in response.json()["detail"]}


# --- Routing -----------------------------------------------------------------


def test_openapi_exposes_exactly_the_documented_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]

    routes = {(method.upper(), path) for path, methods in paths.items() for method in methods}

    assert routes == ENDPOINTS


def test_docs_are_served(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200


def test_unknown_path_returns_404(client):
    response = client.post("/events/unknown", json={})

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/health"), ("GET", "/events/extract"), ("GET", "/config/parse")],
)
def test_wrong_method_returns_405(client, method, path):
    response = client.request(method, path)

    assert response.status_code == 405
    assert response.json() == {"detail": "Method Not Allowed"}


# --- GET /health -------------------------------------------------------------


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- POST /config/parse ------------------------------------------------------


def test_config_parse(client):
    response = client.post("/config/parse", json={"yaml_text": CONFIG_YAML})

    assert response.status_code == 200
    assert response.json() == EXPECTED_CONFIG


def test_config_parse_accepts_project_config_file(client):
    yaml_text = (PROJECT_ROOT / "config" / "events.yaml").read_text(encoding="utf-8")

    response = client.post("/config/parse", json={"yaml_text": yaml_text})

    assert response.status_code == 200
    assert set(response.json()) == set(EXPECTED_CONFIG)


# --- POST /dates/calculate ---------------------------------------------------


@pytest.mark.parametrize(
    ("lookahead_weeks", "expected_end"),
    [(1, "2026-10-04"), (3, END_DATE)],
)
def test_dates_calculate(client, lookahead_weeks, expected_end):
    # lookahead_weeks is a query parameter, not a JSON body field.
    response = client.post("/dates/calculate", params={"lookahead_weeks": lookahead_weeks})

    assert response.status_code == 200
    assert response.json() == {"start_date": START_DATE, "end_date": expected_end}


# --- POST /search/context ----------------------------------------------------


def test_search_context(client):
    response = client.post("/search/context", json={"yaml_text": CONFIG_YAML})

    assert response.status_code == 200
    assert response.json() == {
        "config": EXPECTED_CONFIG,
        "start_date": START_DATE,
        "end_date": END_DATE,
    }


# --- POST /search/queries ----------------------------------------------------


def test_search_queries(client):
    response = client.post("/search/queries", json={"yaml_text": CONFIG_YAML})

    queries = response.json()

    assert response.status_code == 200
    assert len(queries) == 154
    assert queries[0] == {
        "search_type": "general",
        "category": "music",
        "location": "Jyväskylä",
        "query": (
            '"Jyväskylä" Finland (keikat OR konsertti OR konsertit OR live-musiikki OR '
            f"live music OR gigs OR concert OR concerts) {START_DATE} {END_DATE}"
        ),
        "source": None,
        "venue": None,
        "start_date": START_DATE,
        "end_date": END_DATE,
    }
    for query in queries:
        assert set(query) == set(queries[0])
        assert (query["start_date"], query["end_date"]) == (START_DATE, END_DATE)
        assert query["query"]


# --- POST /events/extract ----------------------------------------------------


def test_extract_jsonld_event(client):
    html = jsonld_html(
        {
            "@type": "MusicEvent",
            "name": "Neelix",
            "startDate": "2026-10-03T23:00:00",
            "url": "https://example.com/neelix",
            "location": {
                "name": "Apollo Live Club",
                "address": {"addressLocality": "Helsinki", "streetAddress": "Mannerheimintie 16"},
                "geo": {"latitude": "60.1688", "longitude": "24.9398"},
            },
        }
    )

    response = client.post("/events/extract", json={"html": html, "page_url": "https://example.com/list"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "Neelix",
            "startDate": "2026-10-03",
            "endDate": "2026-10-03",
            "time": "23:00",
            "price": None,
            "location": {
                "venue": "Apollo Live Club",
                "city": "Helsinki",
                "address": "Mannerheimintie 16",
                "latitude": 60.1688,
                "longitude": 24.9398,
            },
            "description": None,
            "url": "https://example.com/neelix",
            "sourceUrls": ["https://example.com/neelix"],
            "sourceType": "jsonld",
        }
    ]


def test_extract_real_allevents_page(client):
    html = ALLEVENTS_PAGE_PATH.read_text(encoding="utf-8")

    response = client.post("/events/extract", json={"html": html})

    events = response.json()

    assert response.status_code == 200
    assert len(events) == 15
    assert {event["sourceType"] for event in events} == {"allevents"}


def test_extract_returns_events_with_malformed_or_non_finite_coordinates(client):
    # Regression: non-finite floats cannot be serialized to JSON, so a single
    # "nan"/"inf" coordinate used to turn the whole page into a 500.
    html = jsonld_html(
        *(
            {
                "@type": "Event",
                "name": name,
                "startDate": "2026-10-03",
                "location": {"geo": {"latitude": latitude, "longitude": longitude}},
            }
            for name, latitude, longitude in [
                ("NaN latitude", "nan", "26.1"),
                ("Inf latitude", "inf", "26.1"),
                ("Negative inf longitude", "61.7", "-inf"),
                ("Malformed", "61,7", "unknown"),
                ("Zero", "0", 0),
            ]
        )
    )

    response = client.post("/events/extract", json={"html": html})

    assert response.status_code == 200
    assert [
        (event["name"], event["location"]["latitude"], event["location"]["longitude"])
        for event in response.json()
    ] == [
        ("NaN latitude", None, 26.1),
        ("Inf latitude", None, 26.1),
        ("Negative inf longitude", 61.7, None),
        ("Malformed", None, None),
        ("Zero", 0.0, 0.0),
    ]


def test_extract_uses_page_url_as_fallback(client):
    html = jsonld_html({"@type": "Event", "name": "No URL", "startDate": "2026-10-03"})

    response = client.post("/events/extract", json={"html": html, "page_url": "https://example.com/list"})

    assert response.json()[0]["sourceUrls"] == ["https://example.com/list"]


@pytest.mark.parametrize(
    "html",
    [
        pytest.param("", id="empty"),
        pytest.param("<html><body>No events</body></html>", id="no-events"),
        pytest.param("<<<script type='application/ld+json'>{broken", id="malformed-html"),
        pytest.param('<script type="application/ld+json">{"@type": "Event",</script>', id="invalid-json-ld"),
    ],
)
def test_extract_without_usable_events_returns_empty_list(client, html):
    response = client.post("/events/extract", json={"html": html})

    assert response.status_code == 200
    assert response.json() == []


# --- POST /events/location ---------------------------------------------------


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        pytest.param(
            {"name": "A", "location": {"city": "Lahti"}},
            {
                "name": "A",
                "location": {"city": "Lahti", "latitude": 60.9827, "longitude": 25.6615},
                "locationStatus": "city_resolved",
                "needsGeocoding": False,
            },
            id="known-city",
        ),
        pytest.param(
            {"name": "A", "location": {"latitude": 0, "longitude": 0}},
            {
                "name": "A",
                "location": {"latitude": 0, "longitude": 0},
                "locationStatus": "coordinates_available",
                "needsGeocoding": False,
            },
            id="zero-coordinates",
        ),
        pytest.param(
            {"name": "A", "location": {"city": "Tampere"}},
            {
                "name": "A",
                "location": {"city": "Tampere"},
                "locationStatus": "needs_geocoding",
                "needsGeocoding": True,
            },
            id="unknown-city",
        ),
        pytest.param(
            {"name": "A", "location": None},
            {"name": "A", "location": {}, "locationStatus": "needs_geocoding", "needsGeocoding": True},
            id="none-location",
        ),
        pytest.param(
            {},
            {"location": {}, "locationStatus": "needs_geocoding", "needsGeocoding": True},
            id="empty-event",
        ),
    ],
)
def test_location(client, event, expected):
    response = client.post("/events/location", json={"event": event})

    assert response.status_code == 200
    assert response.json() == expected


# --- POST /events/filter-radius ----------------------------------------------


def test_filter_radius(client):
    events = [
        event_at("Jyväskylä", 62.2426, 25.7473),
        event_at("Helsinki", 60.1699, 24.9384),
        event_at("No coordinates", None, None),
        event_at("String coordinates", "60.9827", "25.6615"),
    ]

    response = client.post("/events/filter-radius", json={"events": events, **JOUTSA, "radius_km": 100})

    assert response.status_code == 200
    assert [(event["name"], event["distanceKm"]) for event in response.json()] == [
        ("Jyväskylä", 58.8),
        ("String coordinates", 87.9),
    ]


def test_filter_radius_n8n_payload_shape(client):
    # Mirrors the n8n "Python — Filter Events by Radius" JSON body.
    body = {
        "events": [event_at("Joutsa", 61.7417, 26.1142, locationStatus="city_resolved")],
        "center_lat": 61.742667,
        "center_lon": 26.112972,
        "radius_km": 100,
    }

    response = client.post("/events/filter-radius", json=body)

    assert response.status_code == 200
    assert response.json()[0]["distanceKm"] == 0.1


@pytest.mark.parametrize("coordinate", [None, "", "abc", "nan", "inf", "-inf"])
def test_filter_radius_skips_unusable_coordinates(client, coordinate):
    events = [event_at("Bad", coordinate, 26.1), event_at("Good", 61.7, 26.1)]

    response = client.post("/events/filter-radius", json={"events": events, **JOUTSA, "radius_km": 100})

    assert response.status_code == 200
    assert [event["name"] for event in response.json()] == ["Good"]


def test_filter_radius_empty_events(client):
    response = client.post("/events/filter-radius", json={"events": [], **JOUTSA, "radius_km": 100})

    assert response.status_code == 200
    assert response.json() == []


# --- POST /events/filter-date ------------------------------------------------


def test_filter_date(client):
    events = [
        {"name": "Inside", "startDate": "2026-10-01T19:00:00"},
        {"name": "Before", "startDate": "2026-09-27T19:00:00"},
        {"name": "No date"},
        {
            "name": "Long running",
            "startDate": "2026-09-01",
            "endDate": "2026-12-31",
            "description": "Extra show on 2026-10-10.",
        },
    ]

    response = client.post(
        "/events/filter-date",
        json={"events": events, "start_date": START_DATE, "end_date": END_DATE},
    )

    assert response.status_code == 200
    assert response.json() == [
        {"name": "Inside", "startDate": "2026-10-01T19:00:00"},
        {
            "name": "Long running",
            "startDate": "2026-10-10T13:00:00",
            "endDate": "2026-10-10",
            "description": "Extra show on 2026-10-10.",
            "occurrenceDate": "2026-10-10",
        },
    ]


def test_filter_date_empty_events(client):
    response = client.post(
        "/events/filter-date",
        json={"events": [], "start_date": START_DATE, "end_date": END_DATE},
    )

    assert response.status_code == 200
    assert response.json() == []


# --- POST /events/deduplicate ------------------------------------------------


def test_deduplicate(client):
    events = [
        {"name": "Band", "startDate": "2026-10-01T19:00:00", "url": "https://a.example"},
        {"name": "BAND @ Hall", "startDate": "2026-10-01T20:00:00", "url": "https://b.example"},
        {"name": "Other band", "startDate": "2026-10-01T19:00:00", "url": "https://c.example"},
    ]

    response = client.post("/events/deduplicate", json={"events": events})

    results = response.json()

    assert response.status_code == 200
    assert [event["sourceUrls"] for event in results] == [
        ["https://a.example", "https://b.example"],
        ["https://c.example"],
    ]
    assert results[0]["name"] == "BAND @ Hall"


def test_deduplicate_empty_events(client):
    response = client.post("/events/deduplicate", json={"events": []})

    assert response.status_code == 200
    assert response.json() == []


# --- Request validation already enforced by FastAPI/Pydantic -----------------


@pytest.mark.parametrize(
    ("path", "body", "error_type", "location"),
    [
        # Missing required fields
        ("/config/parse", {}, "missing", ("body", "yaml_text")),
        ("/search/context", {}, "missing", ("body", "yaml_text")),
        ("/search/queries", {}, "missing", ("body", "yaml_text")),
        ("/events/extract", {}, "missing", ("body", "html")),
        ("/events/location", {}, "missing", ("body", "event")),
        ("/events/filter-radius", {"events": [], **JOUTSA}, "missing", ("body", "radius_km")),
        ("/events/filter-radius", {"events": [], "radius_km": 100}, "missing", ("body", "center_lat")),
        ("/events/filter-date", {"events": [], "start_date": START_DATE}, "missing", ("body", "end_date")),
        ("/events/deduplicate", {}, "missing", ("body", "events")),
        # Null values
        ("/config/parse", {"yaml_text": None}, "string_type", ("body", "yaml_text")),
        ("/events/extract", {"html": None}, "string_type", ("body", "html")),
        ("/events/location", {"event": None}, "dict_type", ("body", "event")),
        ("/events/filter-radius", {"events": [], **JOUTSA, "radius_km": None}, "float_type", ("body", "radius_km")),
        ("/events/filter-date", {"events": [], "start_date": None, "end_date": END_DATE}, "string_type", ("body", "start_date")),
        ("/events/deduplicate", {"events": None}, "list_type", ("body", "events")),
        # Wrong types
        ("/config/parse", {"yaml_text": 123}, "string_type", ("body", "yaml_text")),
        ("/events/extract", {"html": 5}, "string_type", ("body", "html")),
        ("/events/extract", {"html": "", "page_url": 5}, "string_type", ("body", "page_url")),
        ("/events/location", {"event": []}, "dict_type", ("body", "event")),
        ("/events/location", {"event": "x"}, "dict_type", ("body", "event")),
        ("/events/filter-radius", {"events": [], **JOUTSA, "radius_km": "far"}, "float_parsing", ("body", "radius_km")),
        ("/events/filter-radius", {"events": {"a": 1}, **JOUTSA, "radius_km": 100}, "list_type", ("body", "events")),
        ("/events/filter-radius", {"events": ["x"], **JOUTSA, "radius_km": 100}, "dict_type", ("body", "events", 0)),
        ("/events/filter-date", {"events": [], "start_date": 20260928, "end_date": END_DATE}, "string_type", ("body", "start_date")),
        ("/events/deduplicate", {"events": [1]}, "dict_type", ("body", "events", 0)),
    ],
)
def test_request_validation_returns_422(client, path, body, error_type, location):
    response = client.post(path, json=body)

    assert response.status_code == 422
    assert (error_type, location) in validation_errors(response)


def test_location_requires_event_wrapper(client):
    # n8n sends {"event": {...}}; posting the bare event is rejected.
    response = client.post("/events/location", json={"name": "A", "location": {}})

    assert response.status_code == 422
    assert ("missing", ("body", "event")) in validation_errors(response)


@pytest.mark.parametrize(
    ("params", "error_type"),
    [
        pytest.param({}, "missing", id="missing"),
        pytest.param({"lookahead_weeks": "abc"}, "int_parsing", id="not-integer"),
        pytest.param({"lookahead_weeks": "2.5"}, "int_parsing", id="fractional"),
    ],
)
def test_dates_calculate_query_parameter_validation(client, params, error_type):
    response = client.post("/dates/calculate", params=params)

    assert response.status_code == 422
    assert (error_type, ("query", "lookahead_weeks")) in validation_errors(response)


def test_dates_calculate_ignores_json_body(client):
    response = client.post("/dates/calculate", json={"lookahead_weeks": 3})

    assert response.status_code == 422
    assert ("missing", ("query", "lookahead_weeks")) in validation_errors(response)


def test_malformed_json_body_returns_422(client):
    response = client.post(
        "/config/parse",
        content="not json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "json_invalid"


def test_form_encoded_body_returns_422(client):
    response = client.post("/config/parse", data={"yaml_text": CONFIG_YAML})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "model_attributes_type"


def test_numeric_strings_are_coerced_for_float_fields(client):
    body = {
        "events": [event_at("Joutsa", 61.7417, 26.1142)],
        "center_lat": "61.742667",
        "center_lon": "26.112972",
        "radius_km": "100",
    }

    response = client.post("/events/filter-radius", json=body)

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_unknown_request_fields_are_ignored(client):
    response = client.post("/events/deduplicate", json={"events": [], "unexpected": True})

    assert response.status_code == 200
    assert response.json() == []


# --- Configuration errors ----------------------------------------------------
# Invalid configuration is a client error: 422 with FastAPI's standard
# validation-error format, located under the "yaml_text" request field.

CONFIG_ENDPOINTS = ["/config/parse", "/search/context", "/search/queries"]
YAML_TEXT = ("body", "yaml_text")


def config_yaml(**overrides) -> str:
    """Return the valid test config with top-level overrides (None removes)."""

    config = yaml.safe_load(CONFIG_YAML)
    config.update(overrides)
    return yaml.safe_dump({key: value for key, value in config.items() if value is not None})


def error_details(response) -> list[dict]:
    assert response.status_code == 422
    details = response.json()["detail"]
    assert isinstance(details, list)
    assert details
    for detail in details:
        assert {"type", "loc", "msg"} <= set(detail)
        assert tuple(detail["loc"][:2]) == YAML_TEXT
    return details


@pytest.mark.parametrize("path", CONFIG_ENDPOINTS)
@pytest.mark.parametrize(
    ("yaml_text", "expected_errors"),
    [
        # Invalid YAML syntax
        pytest.param("center: [unclosed", {("yaml_invalid", YAML_TEXT)}, id="invalid-yaml-syntax"),
        pytest.param("center:\n  name: 'unterminated\n", {("yaml_invalid", YAML_TEXT)}, id="unterminated-string"),
        # YAML that is not a mapping
        pytest.param("just a string", {("config_invalid", YAML_TEXT)}, id="yaml-scalar"),
        pytest.param("42", {("config_invalid", YAML_TEXT)}, id="yaml-number"),
        pytest.param("- concert\n- comedy\n", {("config_invalid", YAML_TEXT)}, id="yaml-list"),
        pytest.param("", {("config_invalid", YAML_TEXT)}, id="empty-yaml"),
        pytest.param("# only a comment\n", {("config_invalid", YAML_TEXT)}, id="comment-only-yaml"),
        # Missing required fields
        pytest.param(
            config_yaml(center=None),
            {("missing", (*YAML_TEXT, "center"))},
            id="missing-center",
        ),
        pytest.param(
            config_yaml(radius_km=None),
            {("missing", (*YAML_TEXT, "radius_km"))},
            id="missing-radius",
        ),
        pytest.param(
            config_yaml(center={"name": "Joutsa", "latitude": 61.7}),
            {("missing", (*YAML_TEXT, "center", "longitude"))},
            id="missing-center-longitude",
        ),
        pytest.param(
            "unrelated: value\n",
            {
                ("missing", (*YAML_TEXT, "center")),
                ("missing", (*YAML_TEXT, "radius_km")),
                ("missing", (*YAML_TEXT, "lookahead_weeks")),
                ("missing", (*YAML_TEXT, "categories")),
            },
            id="all-fields-missing",
        ),
        # Invalid radius_km
        pytest.param(config_yaml(radius_km=0), {("greater_than", (*YAML_TEXT, "radius_km"))}, id="radius-zero"),
        pytest.param(config_yaml(radius_km=-10), {("greater_than", (*YAML_TEXT, "radius_km"))}, id="radius-negative"),
        pytest.param(config_yaml(radius_km="far"), {("float_parsing", (*YAML_TEXT, "radius_km"))}, id="radius-text"),
        # Invalid lookahead_weeks
        pytest.param(
            config_yaml(lookahead_weeks=0),
            {("greater_than", (*YAML_TEXT, "lookahead_weeks"))},
            id="weeks-zero",
        ),
        pytest.param(
            config_yaml(lookahead_weeks=2.5),
            {("int_from_float", (*YAML_TEXT, "lookahead_weeks"))},
            id="weeks-fractional",
        ),
        pytest.param(
            config_yaml(lookahead_weeks="three"),
            {("int_parsing", (*YAML_TEXT, "lookahead_weeks"))},
            id="weeks-text",
        ),
        # Invalid categories
        pytest.param(config_yaml(categories=[]), {("too_short", (*YAML_TEXT, "categories"))}, id="categories-empty"),
        pytest.param(
            config_yaml(categories="concert"),
            {("list_type", (*YAML_TEXT, "categories"))},
            id="categories-not-list",
        ),
        pytest.param(
            config_yaml(categories=["concert", 5]),
            {("string_type", (*YAML_TEXT, "categories", 1))},
            id="categories-non-string-item",
        ),
    ],
)
def test_invalid_config_returns_422(client, path, yaml_text, expected_errors):
    response = client.post(path, json={"yaml_text": yaml_text})

    details = error_details(response)

    assert {(detail["type"], tuple(detail["loc"])) for detail in details} == expected_errors


def test_config_schema_error_details(client):
    response = client.post("/config/parse", json={"yaml_text": config_yaml(radius_km=-10)})

    assert error_details(response) == [
        {
            "type": "greater_than",
            "loc": ["body", "yaml_text", "radius_km"],
            "msg": "Input should be greater than 0",
            "input": -10,
            "ctx": {"gt": 0.0},
        }
    ]


def test_config_yaml_syntax_error_details(client):
    response = client.post("/config/parse", json={"yaml_text": "center: [unclosed"})

    [detail] = error_details(response)

    assert detail["type"] == "yaml_invalid"
    assert detail["msg"].startswith("Invalid YAML: ")
    assert "expected ',' or ']'" in detail["msg"]
    assert detail["ctx"] == {"line": 1, "column": 18}


def test_config_not_mapping_error_details(client):
    response = client.post("/config/parse", json={"yaml_text": "- concert\n"})

    assert error_details(response) == [
        {
            "type": "config_invalid",
            "loc": ["body", "yaml_text"],
            "msg": "Configuration must be a YAML mapping.",
        }
    ]


def test_config_error_with_yaml_specific_values_is_serializable(client):
    # YAML parses unquoted dates into date objects; the error input must still
    # be returned as valid JSON.
    response = client.post("/config/parse", json={"yaml_text": config_yaml(radius_km=date(2026, 10, 1))})

    [detail] = error_details(response)

    assert detail["loc"] == ["body", "yaml_text", "radius_km"]
    assert detail["input"] == "2026-10-01"


@pytest.mark.parametrize("path", CONFIG_ENDPOINTS)
def test_request_level_validation_is_unchanged_for_config_endpoints(client, path):
    # A missing or non-string yaml_text is still rejected by FastAPI itself.
    response = client.post(path, json={"yaml_text": None})

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_type"


# --- Current behavior: known issues ------------------------------------------
# These tests document the existing API contract, including behavior that is
# probably wrong. They are intentionally explicit so that fixing any of these
# issues becomes a deliberate, visible test change.

def test_config_with_huge_lookahead_weeks_returns_500(client):
    # Known issue: lookahead_weeks has no upper bound in the config schema;
    # the date calculation overflows (OverflowError) after validation passes.
    yaml_text = config_yaml(lookahead_weeks=10**9)

    response = client.post("/search/context", json={"yaml_text": yaml_text})

    assert response.status_code == 500


@pytest.mark.parametrize(
    ("lookahead_weeks", "expected_end"),
    [(0, "2026-09-27"), (-2, "2026-09-13")],
)
def test_dates_calculate_accepts_non_positive_weeks(client, lookahead_weeks, expected_end):
    # Known issue: unlike the config schema (lookahead_weeks > 0), the query
    # parameter is unconstrained, producing an end date before the start date.
    response = client.post("/dates/calculate", params={"lookahead_weeks": lookahead_weeks})

    assert response.status_code == 200
    assert response.json() == {"start_date": START_DATE, "end_date": expected_end}


def test_dates_calculate_huge_weeks_returns_500(client):
    # Known issue: an unbounded integer overflows the date calculation.
    response = client.post("/dates/calculate", params={"lookahead_weeks": 10**9})

    assert response.status_code == 500


@pytest.mark.parametrize(
    ("radius_km", "expected_names"),
    [
        # Known issue: radius_km is not required to be positive or finite.
        pytest.param(-5, [], id="negative"),
        pytest.param("nan", [], id="nan-drops-everything"),
        pytest.param("inf", ["Joutsa", "Sydney"], id="inf-keeps-everything"),
    ],
)
def test_filter_radius_accepts_invalid_radius(client, radius_km, expected_names):
    events = [event_at("Joutsa", 61.7417, 26.1142), event_at("Sydney", -33.8688, 151.2093)]

    response = client.post("/events/filter-radius", json={"events": events, **JOUTSA, "radius_km": radius_km})

    assert response.status_code == 200
    assert [event["name"] for event in response.json()] == expected_names


@pytest.mark.parametrize(
    ("center_lat", "expected_status"),
    [
        # Known issue: the center is not range- or finiteness-checked.
        pytest.param(500, 200, id="out-of-range"),
        pytest.param("nan", 200, id="nan"),
        pytest.param("inf", 500, id="inf-crashes-haversine"),
    ],
)
def test_filter_radius_accepts_invalid_center(client, center_lat, expected_status):
    body = {
        "events": [event_at("Joutsa", 61.7417, 26.1142)],
        "center_lat": center_lat,
        "center_lon": 26.112972,
        "radius_km": 100,
    }

    response = client.post("/events/filter-radius", json=body)

    assert response.status_code == expected_status


@pytest.mark.parametrize(
    ("start_date", "end_date"),
    [
        # Known issue: start_date/end_date are plain strings compared
        # lexicographically; they are never parsed or checked for order.
        pytest.param("next monday", "later", id="not-dates"),
        pytest.param("28.9.2026", "18.10.2026", id="finnish-format"),
        pytest.param(END_DATE, START_DATE, id="reversed"),
    ],
)
def test_filter_date_accepts_invalid_date_strings(client, start_date, end_date):
    events = [{"name": "Inside", "startDate": "2026-10-01"}]

    response = client.post(
        "/events/filter-date",
        json={"events": events, "start_date": start_date, "end_date": end_date},
    )

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    ("path", "body"),
    [
        # Known issue: events are typed as plain dicts, so malformed event
        # contents reach the domain functions and crash them.
        pytest.param(
            "/events/location",
            {"event": {"location": "Helsinki"}},
            id="location-string-resolve",
        ),
        pytest.param(
            "/events/filter-radius",
            {"events": [{"location": "Helsinki"}], **JOUTSA, "radius_km": 100},
            id="location-string-radius",
        ),
        pytest.param(
            "/events/filter-date",
            {"events": [{"startDate": 20261001}], "start_date": START_DATE, "end_date": END_DATE},
            id="start-date-number-date-filter",
        ),
        pytest.param(
            "/events/filter-date",
            {
                "events": [{"startDate": "2026-01-01", "endDate": "2027-01-01", "description": 5}],
                "start_date": START_DATE,
                "end_date": END_DATE,
            },
            id="description-number-date-filter",
        ),
        pytest.param(
            "/events/deduplicate",
            {"events": [{"name": "A", "startDate": 1}]},
            id="start-date-number-deduplicate",
        ),
        pytest.param(
            "/events/deduplicate",
            {"events": [{"name": "A", "startDate": "2026-10-01"}, {"name": "A", "startDate": "2026-10-01", "location": None}]},
            id="duplicate-with-none-location",
        ),
    ],
)
def test_malformed_event_contents_return_500(client, path, body):
    response = client.post(path, json=body)

    assert response.status_code == 500


def test_deduplicate_splits_string_source_urls_into_characters(client):
    # Known issue: sourceUrls is assumed to be a list; a string is iterated.
    events = [{"name": "A", "startDate": "2026-10-01", "url": "u", "sourceUrls": "abc"}]

    response = client.post("/events/deduplicate", json={"events": events})

    assert response.status_code == 200
    assert response.json()[0]["sourceUrls"] == ["a", "b", "c", "u"]


def test_extract_without_page_url_leaves_events_without_source(client):
    # Known issue (n8n contract): the workflow posts only {"html": ...}, so
    # JSON-LD events without their own url have no url or sourceUrls.
    html = jsonld_html({"@type": "Event", "name": "No URL", "startDate": "2026-10-03"})

    response = client.post("/events/extract", json={"html": html})

    event = response.json()[0]
    assert (event["url"], event["sourceUrls"]) == (None, [])


@pytest.mark.parametrize("path", sorted(path for method, path in ENDPOINTS if method == "POST"))
def test_endpoints_declare_no_response_schema(client, path):
    # Known issue: no response models are declared, so the OpenAPI document
    # (and Swagger UI) does not describe any response body.
    operation = client.get("/openapi.json").json()["paths"][path]["post"]

    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {}
