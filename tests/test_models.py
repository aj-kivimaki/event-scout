import copy
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.event_digest.extraction import extract_event_data
from src.event_digest.models import Event, Location, validate_event, validate_events

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Real event shapes observed in the pipeline.
EXTRACTED_JSONLD_EVENT = {
    "name": "Jukka Poika - Kuusamo - Restaurant Zone - Sep 23, 2026",
    "startDate": "2026-09-23",
    "endDate": "2026-09-23",
    "time": "23:00",
    "price": None,
    "location": {
        "venue": "Restaurant Zone",
        "city": "Kuusamo",
        "address": "13 Rukankyläntie",
        "latitude": 66.1681,
        "longitude": 29.1392,
    },
    "description": "Jukka Poika at Restaurant Zone on Sep 23, 2026",
    "url": "https://www.jambase.com/show/jukka-poika-restaurant-zone-20260923",
    "sourceUrls": ["https://www.jambase.com/show/jukka-poika-restaurant-zone-20260923"],
    "sourceType": "jsonld",
}

EXTRACTED_ALLEVENTS_EVENT = {
    "name": "Saimaa / Lutakko",
    "startDate": "2026-10-16",
    "endDate": "2026-10-16",
    "time": "19:00",
    "price": None,
    "location": {
        "venue": "Lutakonaukio 3, 40100 Jyväskylä, Finland",
        "city": "Jyväskylä",
        "address": "Lutakonaukio 3, FI-40100 Jyväskylä, Suomi",
        "latitude": 62.239262,
        "longitude": 25.75432,
    },
    "description": None,
    "url": "https://allevents.in/jyv%C3%A4skyl%C3%A4/saimaa-lutakko/200030054049339",
    "sourceUrls": ["https://allevents.in/jyv%C3%A4skyl%C3%A4/saimaa-lutakko/200030054049339"],
    "sourceType": "allevents",
    "eventId": "200030054049339",
}

# Output of the n8n "Python — Deduplicate Events" step (test-data run).
PROCESSED_EVENT = {
    "name": "Future Palace - Jyvaskyla - Lutakko - Oct 2, 2026",
    "startDate": "2026-10-02",
    "endDate": "2026-10-02",
    "time": "19:00",
    "price": None,
    "location": {
        "venue": "Lutakko",
        "city": "Jyvaskyla",
        "address": "Lutakonaukio 3",
        "latitude": 62.2392,
        "longitude": 25.7546,
    },
    "description": "Future Palace at Lutakko on Oct 2, 2026",
    "url": "https://www.jambase.com/show/future-palace-lutakko-20261002",
    "sourceUrls": [
        "https://www.jambase.com/show/future-palace-lutakko-20261002",
        "https://www.songkick.com/concerts/future-palace",
    ],
    "sourceType": "jsonld",
    "locationStatus": "coordinates_available",
    "needsGeocoding": False,
    "distanceKm": 58.3,
}

OCCURRENCE_EVENT = {
    "name": "Exhibition",
    "startDate": "2026-10-10T13:00:00",
    "endDate": "2026-10-10",
    "time": None,
    "description": "Also on 2026-10-10.",
    "occurrenceDate": "2026-10-10",
}


# --- Location ----------------------------------------------------------------


def test_location_valid():
    location = Location.model_validate(EXTRACTED_JSONLD_EVENT["location"])

    assert location.city == "Kuusamo"
    assert location.latitude == 66.1681


def test_location_all_fields_optional():
    assert Location.model_validate({}).model_dump(exclude_unset=True) == {}


def test_location_preserves_unknown_fields():
    location = Location.model_validate({"city": "Joutsa", "postalCode": "19650", "geo": {"x": 1}})

    assert location.model_dump(exclude_unset=True) == {
        "city": "Joutsa",
        "postalCode": "19650",
        "geo": {"x": 1},
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(0, 0.0, id="zero"),
        pytest.param("0", 0.0, id="zero-string"),
        pytest.param(-33.8688, -33.8688, id="negative"),
        pytest.param(61, 61.0, id="int"),
        pytest.param("61.7417", 61.7417, id="numeric-string"),
        pytest.param(None, None, id="none"),
    ],
)
def test_location_accepts_valid_coordinates(value, expected):
    location = Location.model_validate({"latitude": value})

    assert location.latitude == expected


@pytest.mark.parametrize(
    ("value", "error_type"),
    [
        pytest.param(math.nan, "finite_number", id="nan"),
        pytest.param(math.inf, "finite_number", id="inf"),
        pytest.param("-inf", "finite_number", id="negative-inf-string"),
        pytest.param("", "float_parsing", id="empty-string"),
        pytest.param("61,7", "float_parsing", id="decimal-comma"),
        pytest.param([61.7], "float_type", id="list"),
    ],
)
def test_location_rejects_invalid_coordinates(value, error_type):
    with pytest.raises(ValidationError) as exc_info:
        Location.model_validate({"latitude": value})

    assert exc_info.value.errors()[0]["type"] == error_type


# --- Event -------------------------------------------------------------------


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(EXTRACTED_JSONLD_EVENT, id="extracted-jsonld"),
        pytest.param(EXTRACTED_ALLEVENTS_EVENT, id="extracted-allevents"),
        pytest.param(PROCESSED_EVENT, id="processed"),
        pytest.param(OCCURRENCE_EVENT, id="date-occurrence"),
    ],
)
def test_event_real_shapes_round_trip_unchanged(event):
    assert validate_event(copy.deepcopy(event)) == event


def test_event_all_fields_optional():
    assert Event.model_validate({}).model_dump(exclude_unset=True) == {}


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        pytest.param(None, {"location": None}, id="none"),
        pytest.param({}, {"location": {}}, id="empty"),
    ],
)
def test_event_accepts_missing_or_empty_location(location, expected):
    assert validate_event({"location": location}) == expected


def test_event_without_location_key_stays_without_location():
    assert validate_event({"name": "A"}) == {"name": "A"}


def test_event_preserves_unknown_fields_at_both_levels():
    event = {
        "name": "A",
        "fetchIndex": 3,
        "custom": {"nested": [1, None]},
        "location": {"city": "Joutsa", "postalCode": "19650"},
    }

    assert validate_event(event) == event


def test_event_dump_does_not_add_unset_fields():
    result = validate_event({"name": "A", "location": {"city": "Lahti"}})

    assert result == {"name": "A", "location": {"city": "Lahti"}}


@pytest.mark.parametrize("price", ["25.00", 15, 25.5, None])
def test_event_price_keeps_type(price):
    result = validate_event({"price": price})

    assert result["price"] == price
    assert type(result["price"]) is type(price)


@pytest.mark.parametrize(
    ("event", "error_location"),
    [
        pytest.param({"location": "Helsinki"}, ("location",), id="location-string"),
        pytest.param({"location": ["Helsinki"]}, ("location",), id="location-list"),
        pytest.param({"location": 42}, ("location",), id="location-number"),
        pytest.param({"sourceUrls": "https://a.example"}, ("sourceUrls",), id="source-urls-string"),
        pytest.param({"sourceUrls": ["https://a.example", None]}, ("sourceUrls", 1), id="source-urls-null-item"),
        pytest.param({"startDate": 20261001}, ("startDate",), id="start-date-number"),
        pytest.param({"name": 5}, ("name",), id="name-number"),
        pytest.param({"eventId": 123}, ("eventId",), id="event-id-number"),
        pytest.param({"price": {"amount": 5}}, ("price", "str"), id="price-object"),
        pytest.param({"distanceKm": "far"}, ("distanceKm",), id="distance-text"),
        pytest.param({"distanceKm": math.inf}, ("distanceKm",), id="distance-inf"),
        pytest.param({"location": {"longitude": "nan"}}, ("location", "longitude"), id="nested-coordinate"),
    ],
)
def test_event_rejects_structurally_invalid_fields(event, error_location):
    with pytest.raises(ValidationError) as exc_info:
        validate_event(event)

    assert error_location in [tuple(error["loc"]) for error in exc_info.value.errors()]


def test_event_source_urls_stays_a_list():
    urls = ["https://a.example", "https://b.example"]

    assert validate_event({"sourceUrls": urls})["sourceUrls"] == urls


# --- validate_events ---------------------------------------------------------


def test_validate_events_keeps_valid_events_in_order():
    events = [{"name": "A"}, {"name": "B"}, {"name": "C"}]

    assert validate_events(events) == events


def test_validate_events_skips_invalid_events():
    events = [
        {"name": "A"},
        {"name": "Bad", "location": "Helsinki"},
        {"name": "B"},
        {"name": "Worse", "startDate": 1},
    ]

    assert validate_events(events) == [{"name": "A"}, {"name": "B"}]


def test_validate_events_empty_list():
    assert validate_events([]) == []


def test_validate_events_returns_new_dictionaries():
    events = [{"name": "A", "location": {"city": "Joutsa"}}]
    original = copy.deepcopy(events)

    result = validate_events(events)

    assert events == original
    assert result[0] is not events[0]
    assert result[0]["location"] is not events[0]["location"]


def test_validate_events_logs_skipped_events(caplog):
    events = [{"name": "A"}, {"name": "Bad", "sourceUrls": "abc"}]

    with caplog.at_level("WARNING", logger="src.event_digest.models"):
        validate_events(events)

    assert [record.getMessage() for record in caplog.records] == [
        "Skipping invalid event at index 1: sourceUrls: Input should be a valid list",
        "Validated events: 2 received, 1 valid, 1 skipped",
    ]


def test_validate_events_logs_nothing_for_valid_batch(caplog):
    with caplog.at_level("WARNING", logger="src.event_digest.models"):
        validate_events([{"name": "A"}])

    assert caplog.records == []


@pytest.mark.parametrize(
    ("path", "page_url"),
    [
        ("config/test-event-page.html", "https://www.jambase.com/concerts/fi"),
        ("tests/fixtures/allevents-jyvaskyla-music.html", "https://allevents.in/jyv%c3%a4skyl%c3%a4/music"),
    ],
)
def test_all_real_extracted_events_validate_unchanged(path, page_url):
    events = extract_event_data((PROJECT_ROOT / path).read_text(encoding="utf-8"), page_url)

    assert events
    assert validate_events(events) == events
