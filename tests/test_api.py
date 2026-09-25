"""Tests for the FastAPI boundary in src/event_digest/api.py.

These tests document the current HTTP contract: happy paths for every
endpoint, the request validation the Pydantic models already enforce, and
(in the known-issues section) malformed input that currently reaches the
domain functions.
"""

import json
import math
from datetime import date
from functools import partial
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config import schema
from src.event_digest import api, search_context
from src.event_digest.dates import calculate_date_range, filter_events_by_date, max_lookahead_weeks
from src.event_digest.deduplication import deduplicate_events
from src.event_digest.extraction import extract_event_data
from src.event_digest.locations import filter_events_by_radius, resolve_event_location

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALLEVENTS_PAGE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "allevents-jyvaskyla-music.html"

# Friday; the search period is therefore Monday 2026-09-28 to Sunday 2026-10-18.
FIXED_TODAY = date(2026, 9, 25)
START_DATE = "2026-09-28"
END_DATE = "2026-10-18"
# Largest lookahead whose end date fits before date.max from START_DATE.
MAX_LOOKAHEAD_WEEKS = 416024

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

    pin_today(monkeypatch, FIXED_TODAY)


def pin_today(monkeypatch, today: date) -> None:
    pinned_range = partial(calculate_date_range, today=today)
    pinned_max = partial(max_lookahead_weeks, today=today)
    monkeypatch.setattr(api, "calculate_date_range", pinned_range)
    monkeypatch.setattr(search_context, "calculate_date_range", pinned_range)
    monkeypatch.setattr(api, "max_lookahead_weeks", pinned_max)
    monkeypatch.setattr(schema, "max_lookahead_weeks", pinned_max)


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
        pytest.param({"lookahead_weeks": 0}, "greater_than", id="zero"),
        pytest.param({"lookahead_weeks": -1}, "greater_than", id="negative"),
        pytest.param({"lookahead_weeks": MAX_LOOKAHEAD_WEEKS + 1}, "less_than_equal", id="past-max-date"),
        pytest.param({"lookahead_weeks": 10**9}, "less_than_equal", id="timedelta-overflow"),
        pytest.param({"lookahead_weeks": 10**30}, "less_than_equal", id="huge-integer"),
    ],
)
def test_dates_calculate_query_parameter_validation(client, params, error_type):
    response = client.post("/dates/calculate", params=params)

    assert response.status_code == 422
    assert (error_type, ("query", "lookahead_weeks")) in validation_errors(response)


def test_dates_calculate_non_positive_error_details(client):
    response = client.post("/dates/calculate", params={"lookahead_weeks": 0})

    assert response.json() == {
        "detail": [
            {
                "type": "greater_than",
                "loc": ["query", "lookahead_weeks"],
                "msg": "Input should be greater than 0",
                "input": "0",
                "ctx": {"gt": 0},
            }
        ]
    }


def test_dates_calculate_accepts_largest_representable_range(client):
    # The upper bound is technical: the end date must not pass date.max
    # (9999-12-31). With the pinned start date 2026-09-28 that is 416024 weeks.
    response = client.post("/dates/calculate", params={"lookahead_weeks": MAX_LOOKAHEAD_WEEKS})

    assert response.status_code == 200
    assert response.json() == {"start_date": START_DATE, "end_date": "9999-12-26"}


def test_dates_calculate_overflow_error_details(client):
    response = client.post("/dates/calculate", params={"lookahead_weeks": MAX_LOOKAHEAD_WEEKS + 1})

    assert response.json() == {
        "detail": [
            {
                "type": "less_than_equal",
                "loc": ["query", "lookahead_weeks"],
                "msg": f"Input should be less than or equal to {MAX_LOOKAHEAD_WEEKS}",
                "input": str(MAX_LOOKAHEAD_WEEKS + 1),
                "ctx": {"le": MAX_LOOKAHEAD_WEEKS},
            }
        ]
    }


def test_dates_calculate_upper_bound_follows_start_date(client, monkeypatch):
    # One week later, one week less fits before date.max.
    pin_today(monkeypatch, date(2026, 10, 2))

    at_old_max = client.post("/dates/calculate", params={"lookahead_weeks": MAX_LOOKAHEAD_WEEKS})
    at_new_max = client.post("/dates/calculate", params={"lookahead_weeks": MAX_LOOKAHEAD_WEEKS - 1})

    assert at_old_max.status_code == 422
    assert at_new_max.status_code == 200


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
        pytest.param(
            config_yaml(radius_km=math.inf),
            {("finite_number", (*YAML_TEXT, "radius_km"))},
            id="radius-inf",
        ),
        pytest.param(
            config_yaml(radius_km=-math.inf),
            {("finite_number", (*YAML_TEXT, "radius_km"))},
            id="radius-negative-inf",
        ),
        pytest.param(
            config_yaml(radius_km=math.nan),
            {("finite_number", (*YAML_TEXT, "radius_km"))},
            id="radius-nan",
        ),
        # Invalid lookahead_weeks
        pytest.param(
            config_yaml(lookahead_weeks=0),
            {("greater_than", (*YAML_TEXT, "lookahead_weeks"))},
            id="weeks-zero",
        ),
        pytest.param(
            config_yaml(lookahead_weeks=-1),
            {("greater_than", (*YAML_TEXT, "lookahead_weeks"))},
            id="weeks-negative",
        ),
        pytest.param(
            config_yaml(lookahead_weeks=MAX_LOOKAHEAD_WEEKS + 1),
            {("less_than_equal", (*YAML_TEXT, "lookahead_weeks"))},
            id="weeks-past-max-date",
        ),
        pytest.param(
            config_yaml(lookahead_weeks=10**9),
            {("less_than_equal", (*YAML_TEXT, "lookahead_weeks"))},
            id="weeks-huge",
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


def test_config_lookahead_overflow_error_details(client):
    response = client.post("/config/parse", json={"yaml_text": config_yaml(lookahead_weeks=10**9)})

    assert error_details(response) == [
        {
            "type": "less_than_equal",
            "loc": ["body", "yaml_text", "lookahead_weeks"],
            "msg": f"Input should be less than or equal to {MAX_LOOKAHEAD_WEEKS}",
            "input": 10**9,
            "ctx": {"le": MAX_LOOKAHEAD_WEEKS},
        }
    ]


@pytest.mark.parametrize(
    ("lookahead_weeks", "expected_end"),
    [
        pytest.param(1, "2026-10-04", id="one-week"),
        pytest.param(3, END_DATE, id="three-weeks"),
        pytest.param(MAX_LOOKAHEAD_WEEKS, "9999-12-26", id="largest-representable"),
    ],
)
def test_config_valid_lookahead_weeks(client, lookahead_weeks, expected_end):
    yaml_text = config_yaml(lookahead_weeks=lookahead_weeks)

    parsed = client.post("/config/parse", json={"yaml_text": yaml_text})
    context = client.post("/search/context", json={"yaml_text": yaml_text})
    queries = client.post("/search/queries", json={"yaml_text": yaml_text})

    assert parsed.status_code == 200
    assert parsed.json()["lookahead_weeks"] == lookahead_weeks
    assert context.status_code == 200
    assert (context.json()["start_date"], context.json()["end_date"]) == (START_DATE, expected_end)
    assert queries.status_code == 200
    assert len(queries.json()) == 154
    assert {(query["start_date"], query["end_date"]) for query in queries.json()} == {(START_DATE, expected_end)}


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


# --- Event validation --------------------------------------------------------
# Batch endpoints validate events individually: invalid events are skipped and
# valid events continue. /events/location validates its single event and
# returns 422 for an invalid one.

BATCH_ENDPOINTS = {
    "/events/filter-radius": {**JOUTSA, "radius_km": 100},
    "/events/filter-date": {"start_date": START_DATE, "end_date": END_DATE},
    "/events/deduplicate": {},
}

MALFORMED_EVENTS = [
    pytest.param({"location": "Helsinki"}, id="location-string"),
    pytest.param({"location": ["Helsinki"]}, id="location-list"),
    pytest.param({"startDate": 20261001}, id="start-date-number"),
    pytest.param({"description": 5}, id="description-number"),
    pytest.param({"sourceUrls": "https://a.example"}, id="source-urls-string"),
    pytest.param({"sourceUrls": ["https://a.example", None]}, id="source-urls-null-item"),
    pytest.param({"price": {"amount": 5}}, id="price-object"),
    pytest.param({"location": {"latitude": "abc", "longitude": 26.1}}, id="latitude-text"),
    pytest.param({"location": {"latitude": "nan", "longitude": 26.1}}, id="latitude-nan"),
    pytest.param({"needsGeocoding": "maybe"}, id="needs-geocoding-text"),
]


def valid_event(name: str, **fields) -> dict:
    """An event that passes every batch endpoint unchanged."""

    return {
        "name": name,
        "startDate": "2026-10-01",
        "endDate": "2026-10-01",
        "location": {"latitude": 61.7417, "longitude": 26.1142},
        **fields,
    }


def post_batch(client, path: str, events: list[dict]):
    return client.post(path, json={"events": events, **BATCH_ENDPOINTS[path]})


@pytest.mark.parametrize("path", BATCH_ENDPOINTS)
@pytest.mark.parametrize("malformed", MALFORMED_EVENTS)
def test_batch_skips_malformed_event_and_keeps_valid_ones(client, path, malformed):
    events = [
        valid_event("Before"),
        {**valid_event("Malformed"), **malformed},
        valid_event("After", startDate="2026-10-02", endDate="2026-10-02"),
    ]

    response = post_batch(client, path, events)

    assert response.status_code == 200
    assert [event["name"] for event in response.json()] == ["Before", "After"]


def test_batch_logs_skipped_events(client, caplog):
    events = [valid_event("Valid"), {"name": "Bad", "location": "Helsinki"}]

    with caplog.at_level("WARNING", logger="src.event_digest.models"):
        post_batch(client, "/events/deduplicate", events)

    messages = [record.getMessage() for record in caplog.records]
    assert "Skipping invalid event at index 1: location: Input should be a valid dictionary or instance of Location" in messages
    assert "Validated events: 2 received, 1 valid, 1 skipped" in messages


def test_batch_with_only_malformed_events_returns_empty_list(client):
    response = post_batch(client, "/events/deduplicate", [{"startDate": 1}, {"location": "x"}])

    assert response.status_code == 200
    assert response.json() == []


def test_batch_skips_nan_json_literal_instead_of_failing(client):
    # Python's JSON parser accepts the non-standard NaN literal.
    body = (
        '{"events": [{"name": "Bad", "location": {"latitude": NaN, "longitude": 26.1}}, '
        '{"name": "Good", "location": {"latitude": 61.7, "longitude": 26.1}}], '
        '"center_lat": 61.742667, "center_lon": 26.112972, "radius_km": 100}'
    )

    response = client.post(
        "/events/filter-radius",
        content=body,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 200
    assert [event["name"] for event in response.json()] == ["Good"]


def test_source_urls_string_is_not_split_into_characters(client):
    events = [{"name": "A", "startDate": "2026-10-01", "url": "u", "sourceUrls": "abc"}]

    response = post_batch(client, "/events/deduplicate", events)

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("path", BATCH_ENDPOINTS)
@pytest.mark.parametrize(
    "location",
    [
        pytest.param(None, id="none-location"),
        pytest.param({}, id="empty-location"),
    ],
)
def test_batch_accepts_missing_or_empty_location(client, path, location):
    event = {"name": "A", "startDate": "2026-10-01", "location": location}

    response = post_batch(client, path, [event])

    assert response.status_code == 200
    if path == "/events/filter-radius":
        # No coordinates: skipped by the radius filter itself, as before.
        assert response.json() == []
    else:
        assert response.json()[0]["location"] == location


@pytest.mark.parametrize("path", BATCH_ENDPOINTS)
def test_batch_preserves_unknown_fields(client, path):
    event = valid_event(
        "A",
        customField={"nested": [1, 2]},
        fetchIndex=7,
        location={"latitude": 61.7417, "longitude": 26.1142, "postalCode": "19650"},
    )

    response = post_batch(client, path, [event])

    [result] = response.json()
    assert result["customField"] == {"nested": [1, 2]}
    assert result["fetchIndex"] == 7
    assert result["location"]["postalCode"] == "19650"


@pytest.mark.parametrize("path", BATCH_ENDPOINTS)
def test_batch_does_not_add_unset_fields(client, path):
    event = valid_event("A")

    response = post_batch(client, path, [event])

    [result] = response.json()
    added_by_endpoint = {
        "/events/filter-radius": {"distanceKm"},
        "/events/filter-date": set(),
        "/events/deduplicate": {"sourceUrls"},
    }[path]
    assert set(result) == set(event) | added_by_endpoint
    assert set(result["location"]) == {"latitude", "longitude"}


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        pytest.param(0, 0, id="int-zero"),
        pytest.param(0.0, 0.0, id="float-zero"),
        pytest.param("0", "0", id="string-zero"),
    ],
)
def test_zero_coordinates_are_accepted(client, latitude, longitude):
    event = {"name": "Null Island", "location": {"latitude": latitude, "longitude": longitude}}

    location = client.post("/events/location", json={"event": event})
    radius = post_batch(client, "/events/filter-radius", [event])
    far_radius = client.post(
        "/events/filter-radius",
        json={"events": [event], **JOUTSA, "radius_km": 20000},
    )

    assert location.status_code == 200
    assert location.json()["locationStatus"] == "coordinates_available"
    assert location.json()["location"] == {"latitude": 0, "longitude": 0}
    assert radius.json() == []
    assert far_radius.json()[0]["location"] == {"latitude": 0, "longitude": 0}


@pytest.mark.parametrize(
    ("event", "error_type", "location"),
    [
        pytest.param({"location": "Helsinki"}, "model_type", ("body", "event", "location"), id="location-string"),
        pytest.param({"startDate": 20261001}, "string_type", ("body", "event", "startDate"), id="start-date-number"),
        pytest.param(
            {"location": {"latitude": "nan"}},
            "finite_number",
            ("body", "event", "location", "latitude"),
            id="latitude-nan",
        ),
        pytest.param({"sourceUrls": "abc"}, "list_type", ("body", "event", "sourceUrls"), id="source-urls-string"),
    ],
)
def test_location_endpoint_rejects_malformed_event(client, event, error_type, location):
    response = client.post("/events/location", json={"event": event})

    assert response.status_code == 422
    assert (error_type, location) in validation_errors(response)


def test_location_endpoint_preserves_unknown_fields(client):
    event = {"name": "A", "customField": 1, "location": {"city": "Lahti", "postalCode": "15100"}}

    response = client.post("/events/location", json={"event": event})

    assert response.json() == {
        "name": "A",
        "customField": 1,
        "location": {"city": "Lahti", "postalCode": "15100", "latitude": 60.9827, "longitude": 25.6615},
        "locationStatus": "city_resolved",
        "needsGeocoding": False,
    }


def test_real_pages_through_api_match_domain_pipeline(client):
    """The n8n pipeline through the API gives the same result as the domain
    functions called directly, for real extracted events."""

    pages = [
        (PROJECT_ROOT / "config" / "test-event-page.html", "https://www.jambase.com/concerts/fi"),
        (ALLEVENTS_PAGE_PATH, "https://allevents.in/jyv%c3%a4skyl%c3%a4/music"),
    ]

    # Domain pipeline, called directly.
    extracted = []
    for path, page_url in pages:
        extracted.extend(extract_event_data(path.read_text(encoding="utf-8"), page_url))
    expected_counts = [len(extracted)]
    expected = filter_events_by_date(extracted, START_DATE, END_DATE)
    expected_counts.append(len(expected))
    expected = [resolve_event_location(event) for event in expected]
    expected = filter_events_by_radius(expected, JOUTSA["center_lat"], JOUTSA["center_lon"], 100)
    expected_counts.append(len(expected))
    expected = deduplicate_events(expected)
    expected_counts.append(len(expected))

    # Same pipeline through the API, in n8n order.
    events = []
    for path, page_url in pages:
        response = client.post(
            "/events/extract",
            json={"html": path.read_text(encoding="utf-8"), "page_url": page_url},
        )
        events.extend(response.json())
    counts = [len(events)]

    events = client.post(
        "/events/filter-date",
        json={"events": events, "start_date": START_DATE, "end_date": END_DATE},
    ).json()
    counts.append(len(events))

    events = [client.post("/events/location", json={"event": event}).json() for event in events]
    events = client.post("/events/filter-radius", json={"events": events, **JOUTSA, "radius_km": 100}).json()
    counts.append(len(events))

    events = client.post("/events/deduplicate", json={"events": events}).json()
    counts.append(len(events))

    assert counts == expected_counts
    # JamBase alone: 181 -> 71 -> 8 -> 6 (as in the n8n test-data run).
    assert counts == [196, 76, 13, 11]
    assert events == json.loads(json.dumps(expected))


def test_deduplicate_duplicate_with_none_location(client):
    # Regression: merging a duplicate with "location": None used to return 500.
    events = [
        {"name": "A", "startDate": "2026-10-01", "url": "https://a.example"},
        {"name": "A", "startDate": "2026-10-01", "url": "https://b.example", "location": None},
    ]

    response = client.post("/events/deduplicate", json={"events": events})

    assert response.status_code == 200
    assert response.json() == [
        {
            "name": "A",
            "startDate": "2026-10-01",
            "url": "https://a.example",
            "sourceUrls": ["https://a.example", "https://b.example"],
            "location": {},
        }
    ]


# --- Radius filter parameter validation --------------------------------------

JOUTSA_EVENT = event_at("Joutsa", 61.7417, 26.1142)
SYDNEY_EVENT = event_at("Sydney", -33.8688, 151.2093)

NON_FINITE_STRINGS = [
    pytest.param("nan", id="nan"),
    pytest.param("NaN", id="nan-mixed-case"),
    pytest.param("inf", id="inf"),
    pytest.param("-inf", id="negative-inf"),
    pytest.param("Infinity", id="infinity"),
    pytest.param("-Infinity", id="negative-infinity"),
]


def radius_request(**overrides) -> dict:
    return {"events": [JOUTSA_EVENT, SYDNEY_EVENT], **JOUTSA, "radius_km": 100, **overrides}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("center_lat", -90, id="latitude-min"),
        pytest.param("center_lat", 90, id="latitude-max"),
        pytest.param("center_lat", 0, id="latitude-zero"),
        pytest.param("center_lon", -180, id="longitude-min"),
        pytest.param("center_lon", 180, id="longitude-max"),
        pytest.param("center_lon", 0, id="longitude-zero"),
        pytest.param("radius_km", 100, id="radius-normal"),
        pytest.param("radius_km", 0.001, id="radius-tiny"),
        pytest.param("radius_km", 1e300, id="radius-very-large"),
    ],
)
def test_filter_radius_accepts_valid_parameters(client, field, value):
    response = client.post("/events/filter-radius", json=radius_request(**{field: value}))

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("field", "value", "error_type"),
    [
        pytest.param("center_lat", -90.1, "greater_than_equal", id="latitude-below-min"),
        pytest.param("center_lat", 90.1, "less_than_equal", id="latitude-above-max"),
        pytest.param("center_lat", 500, "less_than_equal", id="latitude-far-out-of-range"),
        pytest.param("center_lon", -180.1, "greater_than_equal", id="longitude-below-min"),
        pytest.param("center_lon", 180.1, "less_than_equal", id="longitude-above-max"),
        pytest.param("radius_km", 0, "greater_than", id="radius-zero"),
        pytest.param("radius_km", -5, "greater_than", id="radius-negative"),
    ],
)
def test_filter_radius_rejects_out_of_range_parameters(client, field, value, error_type):
    response = client.post("/events/filter-radius", json=radius_request(**{field: value}))

    assert response.status_code == 422
    assert validation_errors(response) == {(error_type, ("body", field))}


@pytest.mark.parametrize("value", NON_FINITE_STRINGS)
@pytest.mark.parametrize("field", ["center_lat", "center_lon", "radius_km"])
def test_filter_radius_rejects_non_finite_parameters(client, field, value):
    response = client.post("/events/filter-radius", json=radius_request(**{field: value}))

    assert response.status_code == 422
    assert validation_errors(response) == {("finite_number", ("body", field))}


def test_filter_radius_parameter_error_details(client):
    response = client.post("/events/filter-radius", json=radius_request(center_lat=90.1))

    assert response.json() == {
        "detail": [
            {
                "type": "less_than_equal",
                "loc": ["body", "center_lat"],
                "msg": "Input should be less than or equal to 90",
                "input": 90.1,
                "ctx": {"le": 90},
            }
        ]
    }


def test_filter_radius_reports_all_invalid_parameters(client):
    response = client.post(
        "/events/filter-radius",
        json=radius_request(center_lat=91, center_lon="inf", radius_km=0),
    )

    assert validation_errors(response) == {
        ("less_than_equal", ("body", "center_lat")),
        ("finite_number", ("body", "center_lon")),
        ("greater_than", ("body", "radius_km")),
    }


def test_filter_radius_valid_request_result_is_unchanged(client):
    response = client.post("/events/filter-radius", json=radius_request())

    assert response.json() == filter_events_by_radius(
        [JOUTSA_EVENT, SYDNEY_EVENT],
        JOUTSA["center_lat"],
        JOUTSA["center_lon"],
        100,
    )
    assert [(event["name"], event["distanceKm"]) for event in response.json()] == [("Joutsa", 0.1)]


def test_filter_radius_very_large_radius_keeps_distant_events(client):
    response = client.post("/events/filter-radius", json=radius_request(radius_km=20000))

    assert [(event["name"], event["distanceKm"]) for event in response.json()] == [
        ("Joutsa", 0.1),
        ("Sydney", 15100.1),
    ]


# --- Non-finite numbers in validation errors ---------------------------------
# Python's JSON parser accepts NaN/Infinity literals and overflows 1e400 to
# infinity. Validation rejects them, and the rejected value is echoed as a
# string ("nan", "inf", "-inf") so the 422 response is valid JSON.

NON_FINITE_JSON_NUMBERS = [
    pytest.param("NaN", "nan", id="nan-literal"),
    pytest.param("Infinity", "inf", id="infinity-literal"),
    pytest.param("-Infinity", "-inf", id="negative-infinity-literal"),
    pytest.param("1e400", "inf", id="overflowing-number"),
    pytest.param("-1e400", "-inf", id="negative-overflowing-number"),
]


def strict_json(response):
    """Parse a response body, rejecting NaN/Infinity tokens."""

    def reject(token):
        raise ValueError(f"non-standard JSON token: {token}")

    return json.loads(response.text, parse_constant=reject)


def post_raw_radius(client, **raw_values):
    values = {"center_lat": "61.742667", "center_lon": "26.112972", "radius_km": "100", **raw_values}
    body = '{"events": [], ' + ", ".join(f'"{key}": {value}' for key, value in values.items()) + "}"
    return client.post("/events/filter-radius", content=body, headers={"content-type": "application/json"})


@pytest.mark.parametrize(("raw_value", "echoed"), NON_FINITE_JSON_NUMBERS)
@pytest.mark.parametrize("field", ["center_lat", "center_lon", "radius_km"])
def test_non_finite_json_number_returns_422(client, field, raw_value, echoed):
    response = post_raw_radius(client, **{field: raw_value})

    assert response.status_code == 422
    assert strict_json(response) == {
        "detail": [
            {
                "type": "finite_number",
                "loc": ["body", field],
                "msg": "Input should be a finite number",
                "input": echoed,
            }
        ]
    }


def test_multiple_non_finite_json_numbers_return_one_422(client):
    response = post_raw_radius(client, center_lat="NaN", center_lon="Infinity", radius_km="-Infinity")

    assert response.status_code == 422
    assert [(error["loc"][-1], error["input"]) for error in strict_json(response)["detail"]] == [
        ("center_lat", "nan"),
        ("center_lon", "inf"),
        ("radius_km", "-inf"),
    ]


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "Infinity"])
def test_non_finite_strings_are_echoed_unchanged(client, value):
    response = client.post("/events/filter-radius", json=radius_request(radius_km=value))

    assert response.status_code == 422
    assert strict_json(response)["detail"] == [
        {
            "type": "finite_number",
            "loc": ["body", "radius_km"],
            "msg": "Input should be a finite number",
            "input": value,
        }
    ]


def test_non_finite_json_number_inside_event_returns_422(client):
    # /events/location formats its own 422 (validation_error_details()).
    response = client.post(
        "/events/location",
        content='{"event": {"name": "A", "location": {"latitude": NaN, "longitude": 26.1}}}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert strict_json(response)["detail"] == [
        {
            "type": "finite_number",
            "loc": ["body", "event", "location", "latitude"],
            "msg": "Input should be a finite number",
            "input": "nan",
        }
    ]


@pytest.mark.parametrize("path", CONFIG_ENDPOINTS)
@pytest.mark.parametrize(
    ("yaml_value", "echoed"),
    [
        pytest.param(".inf", "inf", id="inf"),
        pytest.param("-.inf", "-inf", id="negative-inf"),
        pytest.param(".nan", "nan", id="nan"),
    ],
)
def test_non_finite_config_radius_returns_422(client, path, yaml_value, echoed):
    # YAML's .inf/-.inf/.nan reach config validation as non-finite floats.
    yaml_text = config_yaml().replace("radius_km: 100", f"radius_km: {yaml_value}")

    response = client.post(path, json={"yaml_text": yaml_text})

    assert response.status_code == 422
    assert strict_json(response)["detail"] == [
        {
            "type": "finite_number",
            "loc": ["body", "yaml_text", "radius_km"],
            "msg": "Input should be a finite number",
            "input": echoed,
        }
    ]


def center_yaml(**center) -> str:
    return config_yaml(center={**EXPECTED_CONFIG["center"], **center})


@pytest.mark.parametrize("path", CONFIG_ENDPOINTS)
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
def test_config_center_within_bounds_is_valid(client, path, field, value):
    response = client.post(path, json={"yaml_text": center_yaml(**{field: value})})

    assert response.status_code == 200
    if path != "/search/queries":
        config = response.json() if path == "/config/parse" else response.json()["config"]
        assert config["center"][field] == value


@pytest.mark.parametrize("path", CONFIG_ENDPOINTS)
@pytest.mark.parametrize(
    ("field", "value", "error_type", "echoed"),
    [
        pytest.param("latitude", -90.1, "greater_than_equal", -90.1, id="latitude-below-min"),
        pytest.param("latitude", 90.1, "less_than_equal", 90.1, id="latitude-above-max"),
        pytest.param("longitude", -180.1, "greater_than_equal", -180.1, id="longitude-below-min"),
        pytest.param("longitude", 180.1, "less_than_equal", 180.1, id="longitude-above-max"),
        pytest.param("latitude", math.inf, "finite_number", "inf", id="latitude-inf"),
        pytest.param("latitude", -math.inf, "finite_number", "-inf", id="latitude-negative-inf"),
        pytest.param("latitude", math.nan, "finite_number", "nan", id="latitude-nan"),
        pytest.param("longitude", math.inf, "finite_number", "inf", id="longitude-inf"),
        pytest.param("longitude", -math.inf, "finite_number", "-inf", id="longitude-negative-inf"),
        pytest.param("longitude", math.nan, "finite_number", "nan", id="longitude-nan"),
    ],
)
def test_config_invalid_center_returns_422(client, path, field, value, error_type, echoed):
    response = client.post(path, json={"yaml_text": center_yaml(**{field: value})})

    assert response.status_code == 422
    [detail] = strict_json(response)["detail"]
    assert detail["type"] == error_type
    assert detail["loc"] == ["body", "yaml_text", "center", field]
    assert detail["input"] == echoed


def test_config_center_error_details(client):
    response = client.post("/config/parse", json={"yaml_text": center_yaml(latitude=90.1)})

    assert strict_json(response)["detail"] == [
        {
            "type": "less_than_equal",
            "loc": ["body", "yaml_text", "center", "latitude"],
            "msg": "Input should be less than or equal to 90",
            "input": 90.1,
            "ctx": {"le": 90.0},
        }
    ]


@pytest.mark.parametrize("path", CONFIG_ENDPOINTS)
@pytest.mark.parametrize("radius_km", [0.001, 100, 1e300])
def test_config_finite_positive_radius_is_valid(client, path, radius_km):
    response = client.post(path, json={"yaml_text": config_yaml(radius_km=radius_km)})

    assert response.status_code == 200
    if path != "/search/queries":
        config = response.json() if path == "/config/parse" else response.json()["config"]
        assert config["radius_km"] == radius_km


def test_non_finite_json_number_in_event_batch_is_still_skipped(client):
    # Batch endpoints skip invalid events rather than returning 422.
    body = (
        '{"events": [{"name": "Bad", "location": {"latitude": Infinity, "longitude": 26.1}}, '
        '{"name": "Good", "location": {"latitude": 61.7, "longitude": 26.1}}], '
        '"center_lat": 61.742667, "center_lon": 26.112972, "radius_km": 100}'
    )

    response = client.post("/events/filter-radius", content=body, headers={"content-type": "application/json"})

    assert response.status_code == 200
    assert [event["name"] for event in response.json()] == ["Good"]


def default_handler_app() -> FastAPI:
    """The radius endpoint with FastAPI's default validation handler."""

    plain = FastAPI()
    plain.post("/events/filter-radius")(api.filter_events_radius_endpoint)
    plain.post("/events/deduplicate")(api.deduplicate_events_endpoint)
    return plain


@pytest.mark.parametrize(
    ("path", "body"),
    [
        pytest.param("/events/filter-radius", radius_request(center_lat=91), id="latitude-91"),
        pytest.param("/events/filter-radius", radius_request(center_lon=181), id="longitude-181"),
        pytest.param("/events/filter-radius", radius_request(radius_km=0), id="radius-zero"),
        pytest.param("/events/filter-radius", radius_request(radius_km="far"), id="radius-text"),
        pytest.param("/events/filter-radius", radius_request(radius_km=None), id="radius-null"),
        pytest.param("/events/filter-radius", {"events": [], **JOUTSA}, id="missing-radius"),
        pytest.param("/events/filter-radius", radius_request(events={"a": 1}), id="events-not-list"),
        pytest.param("/events/filter-radius", radius_request(center_lat="nan"), id="nan-string"),
        pytest.param("/events/deduplicate", {}, id="missing-events"),
        pytest.param("/events/deduplicate", {"events": [1]}, id="event-not-object"),
    ],
)
def test_ordinary_validation_errors_match_fastapi_default(client, path, body):
    expected = TestClient(default_handler_app()).post(path, json=body)

    response = client.post(path, json=body)

    assert response.status_code == expected.status_code == 422
    assert response.json() == expected.json()


def test_ordinary_validation_error_body_is_unchanged(client):
    response = client.post("/events/filter-radius", json=radius_request(center_lat=91))

    assert response.json() == {
        "detail": [
            {
                "type": "less_than_equal",
                "loc": ["body", "center_lat"],
                "msg": "Input should be less than or equal to 90",
                "input": 91,
                "ctx": {"le": 90.0},
            }
        ]
    }


# --- Current behavior: known issues ------------------------------------------
# These tests document the existing API contract, including behavior that is
# probably wrong. They are intentionally explicit so that fixing any of these
# issues becomes a deliberate, visible test change.

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
