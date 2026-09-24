import copy
import math

import pytest

from src.event_digest.locations import (
    CITY_COORDINATES,
    _haversine_distance,
    _is_number,
    filter_events_by_radius,
    resolve_event_location,
)

# Configured center (config/events.yaml).
JOUTSA = (61.742667, 26.112972)
RADIUS_KM = 100

EARTH_RADIUS_KM = 6371
ONE_DEGREE_KM = 2 * math.pi * EARTH_RADIUS_KM / 360
HALF_CIRCUMFERENCE_KM = math.pi * EARTH_RADIUS_KM


def make_event(**location) -> dict:
    return {"name": "Test Event", "location": location}


def filter_near_joutsa(events: list[dict], radius_km: float = RADIUS_KM) -> list[dict]:
    return filter_events_by_radius(events, *JOUTSA, radius_km)


# --- _haversine_distance -----------------------------------------------------


def test_haversine_distance_is_zero_for_same_point():
    assert _haversine_distance(*JOUTSA, *JOUTSA) == 0


@pytest.mark.parametrize(
    ("point_a", "point_b", "expected_km"),
    [
        pytest.param((0, 0), (1, 0), ONE_DEGREE_KM, id="one-degree-latitude"),
        pytest.param((0, 0), (0, 1), ONE_DEGREE_KM, id="one-degree-longitude-at-equator"),
        pytest.param((0, 0), (0, 180), HALF_CIRCUMFERENCE_KM, id="antipodal-equator"),
        pytest.param((90, 0), (-90, 0), HALF_CIRCUMFERENCE_KM, id="pole-to-pole"),
    ],
)
def test_haversine_distance_matches_geometric_reference_values(
    point_a,
    point_b,
    expected_km,
):
    assert _haversine_distance(*point_a, *point_b) == pytest.approx(expected_km)


@pytest.mark.parametrize(
    ("city", "expected_km"),
    [
        ("Jyväskylä", 58.8),
        ("Lahti", 87.9),
        ("Helsinki", 186.0),
    ],
)
def test_haversine_distance_from_joutsa_to_known_cities(city, expected_km):
    distance = _haversine_distance(*JOUTSA, *CITY_COORDINATES[city])

    assert distance == pytest.approx(expected_km, abs=0.1)


def test_haversine_distance_is_symmetric():
    helsinki = CITY_COORDINATES["Helsinki"]
    lahti = CITY_COORDINATES["Lahti"]

    assert _haversine_distance(*helsinki, *lahti) == pytest.approx(
        _haversine_distance(*lahti, *helsinki)
    )


def test_haversine_distance_shrinks_longitude_degrees_away_from_equator():
    at_equator = _haversine_distance(0, 0, 0, 1)
    at_joutsa = _haversine_distance(61.7, 26.0, 61.7, 27.0)

    assert at_joutsa == pytest.approx(at_equator * math.cos(math.radians(61.7)), rel=1e-3)


# --- resolve_event_location: existing coordinates -----------------------------


def test_resolve_preserves_existing_coordinates():
    event = make_event(latitude=61.5, longitude=26.5, city="Lahti")

    result = resolve_event_location(event)

    assert result["location"] == {"latitude": 61.5, "longitude": 26.5, "city": "Lahti"}
    assert result["locationStatus"] == "coordinates_available"
    assert result["needsGeocoding"] is False


def test_resolve_accepts_numeric_string_coordinates_without_converting():
    result = resolve_event_location(make_event(latitude="61.5", longitude="26.5"))

    assert result["location"] == {"latitude": "61.5", "longitude": "26.5"}
    assert result["locationStatus"] == "coordinates_available"


def test_resolve_preserves_other_event_and_location_fields():
    event = {
        "name": "Concert",
        "url": "https://example.com/concert",
        "location": {"name": "Hall", "city": "Lahti", "address": "Street 1"},
    }

    result = resolve_event_location(event)

    assert result["name"] == "Concert"
    assert result["url"] == "https://example.com/concert"
    assert result["location"]["name"] == "Hall"
    assert result["location"]["address"] == "Street 1"


# --- resolve_event_location: known-city resolution ----------------------------


@pytest.mark.parametrize("city", sorted(CITY_COORDINATES))
def test_resolve_known_city_to_coordinates(city):
    result = resolve_event_location(make_event(city=city))

    latitude, longitude = CITY_COORDINATES[city]
    assert result["location"] == {"city": city, "latitude": latitude, "longitude": longitude}
    assert result["locationStatus"] == "city_resolved"
    assert result["needsGeocoding"] is False


@pytest.mark.parametrize(
    "location",
    [
        pytest.param({"latitude": 61.5, "city": "Lahti"}, id="latitude-only"),
        pytest.param({"longitude": 26.5, "city": "Lahti"}, id="longitude-only"),
        pytest.param({"latitude": "abc", "longitude": 26.5, "city": "Lahti"}, id="invalid-latitude"),
        pytest.param({"latitude": 61.5, "longitude": None, "city": "Lahti"}, id="none-longitude"),
    ],
)
def test_resolve_incomplete_coordinates_fall_back_to_city(location):
    result = resolve_event_location(make_event(**location))

    assert result["location"]["latitude"] == CITY_COORDINATES["Lahti"][0]
    assert result["location"]["longitude"] == CITY_COORDINATES["Lahti"][1]
    assert result["locationStatus"] == "city_resolved"


# --- resolve_event_location: unknown locations --------------------------------


@pytest.mark.parametrize(
    "event",
    [
        pytest.param({"name": "No location"}, id="no-location-key"),
        pytest.param(make_event(), id="empty-location"),
        pytest.param(make_event(city=""), id="empty-city"),
        pytest.param(make_event(city="Tampere"), id="unknown-city"),
        pytest.param(make_event(city="joutsa"), id="case-sensitive-city"),
        pytest.param(make_event(city=" Joutsa "), id="unstripped-city"),
        pytest.param(make_event(latitude="abc", longitude="def"), id="invalid-coordinates"),
    ],
)
def test_resolve_marks_unresolvable_location_as_needing_geocoding(event):
    result = resolve_event_location(event)

    assert result["locationStatus"] == "needs_geocoding"
    assert result["needsGeocoding"] is True
    assert result["location"] == event.get("location", {})


# --- resolve_event_location: missing or empty location ------------------------


@pytest.mark.parametrize(
    "event",
    [
        pytest.param({"name": "Event"}, id="missing-location"),
        pytest.param({"name": "Event", "location": None}, id="none-location"),
        pytest.param({"name": "Event", "location": {}}, id="empty-location"),
        pytest.param({"name": "Event", "location": ""}, id="empty-string-location"),
        pytest.param({"name": "Event", "location": []}, id="empty-list-location"),
    ],
)
def test_resolve_missing_or_empty_location_needs_geocoding(event):
    result = resolve_event_location(event)

    assert result == {
        "name": "Event",
        "location": {},
        "locationStatus": "needs_geocoding",
        "needsGeocoding": True,
    }


def test_resolve_none_location_matches_missing_location():
    missing = resolve_event_location({"name": "Event"})
    none = resolve_event_location({"name": "Event", "location": None})

    assert none == missing


def test_resolve_none_location_does_not_mutate_input():
    event = {"name": "Event", "location": None}

    result = resolve_event_location(event)

    assert event == {"name": "Event", "location": None}
    assert result["location"] == {}


def test_resolve_valid_location_dictionary_is_copied_unchanged():
    location = {
        "venue": "Joutsa-talo",
        "city": "Tampere",
        "address": "Jousitie 1",
        "latitude": None,
        "longitude": None,
    }

    result = resolve_event_location({"name": "Event", "location": location})

    assert result["location"] == location
    assert result["location"] is not location
    assert result["locationStatus"] == "needs_geocoding"


# --- resolve_event_location: immutability ------------------------------------


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(make_event(latitude=61.5, longitude=26.5), id="coordinates"),
        pytest.param(make_event(city="Lahti"), id="city"),
        pytest.param(make_event(city="Tampere"), id="unknown"),
    ],
)
def test_resolve_does_not_mutate_input(event):
    original = copy.deepcopy(event)

    result = resolve_event_location(event)

    assert event == original
    assert result is not event
    assert result["location"] is not event["location"]


# --- filter_events_by_radius --------------------------------------------------


def test_filter_keeps_nearby_and_drops_distant_events():
    events = [
        make_event(city="Jyväskylä", latitude=62.2426, longitude=25.7473),
        make_event(city="Helsinki", latitude=60.1699, longitude=24.9384),
        make_event(city="Lahti", latitude=60.9827, longitude=25.6615),
    ]

    results = filter_near_joutsa(events)

    assert [event["location"]["city"] for event in results] == ["Jyväskylä", "Lahti"]


def test_filter_adds_distance_rounded_to_one_decimal():
    results = filter_near_joutsa([make_event(latitude=62.2426, longitude=25.7473)])

    assert results[0]["distanceKm"] == 58.8


def test_filter_accepts_numeric_string_coordinates():
    results = filter_near_joutsa([make_event(latitude="61.7", longitude="26.1")])

    assert len(results) == 1
    assert results[0]["location"] == {"latitude": "61.7", "longitude": "26.1"}


def test_filter_includes_event_at_center_with_zero_radius():
    results = filter_near_joutsa([make_event(latitude=JOUTSA[0], longitude=JOUTSA[1])], radius_km=0)

    assert results[0]["distanceKm"] == 0


def test_filter_radius_boundary_is_inclusive():
    point = CITY_COORDINATES["Lahti"]
    exact_distance = _haversine_distance(*JOUTSA, *point)
    event = make_event(latitude=point[0], longitude=point[1])

    assert len(filter_near_joutsa([event], radius_km=exact_distance)) == 1
    assert filter_near_joutsa([event], radius_km=math.nextafter(exact_distance, 0)) == []


@pytest.mark.parametrize(
    "event",
    [
        pytest.param({"name": "No location"}, id="no-location-key"),
        pytest.param({"name": "None location", "location": None}, id="none-location"),
        pytest.param(make_event(), id="empty-location"),
        pytest.param(make_event(city="Joutsa"), id="city-only"),
        pytest.param(make_event(latitude=61.7), id="latitude-only"),
        pytest.param(make_event(longitude=26.1), id="longitude-only"),
        pytest.param(make_event(latitude=None, longitude=26.1), id="none-latitude"),
        pytest.param(make_event(latitude="abc", longitude=26.1), id="non-numeric-string"),
        pytest.param(make_event(latitude=[61.7], longitude=26.1), id="list-latitude"),
        pytest.param(make_event(latitude={}, longitude=26.1), id="dict-latitude"),
    ],
)
def test_filter_skips_events_with_missing_or_invalid_coordinates(event):
    assert filter_near_joutsa([event]) == []


def test_filter_skips_invalid_events_without_affecting_valid_ones():
    events = [
        make_event(latitude="abc", longitude=26.1),
        make_event(latitude=61.7, longitude=26.1),
    ]

    assert len(filter_near_joutsa(events)) == 1


def test_filter_preserves_input_order():
    events = [
        make_event(city="Lahti", latitude=60.9827, longitude=25.6615),
        make_event(city="Joutsa", latitude=61.7417, longitude=26.1142),
        make_event(city="Jyväskylä", latitude=62.2426, longitude=25.7473),
    ]

    results = filter_near_joutsa(events)

    assert [event["location"]["city"] for event in results] == ["Lahti", "Joutsa", "Jyväskylä"]


def test_filter_does_not_mutate_input():
    events = [make_event(latitude=61.7, longitude=26.1)]
    original = copy.deepcopy(events)

    results = filter_near_joutsa(events)

    assert events == original
    assert "distanceKm" not in events[0]
    assert results[0] is not events[0]


def test_filter_handles_empty_input():
    assert filter_near_joutsa([]) == []


# --- Coordinate validation ---------------------------------------------------

NON_FINITE_VALUES = [
    pytest.param(math.nan, id="nan"),
    pytest.param("nan", id="nan-string"),
    pytest.param(math.inf, id="inf"),
    pytest.param("inf", id="inf-string"),
    pytest.param(-math.inf, id="negative-inf"),
    pytest.param("-inf", id="negative-inf-string"),
]


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(0, id="zero"),
        pytest.param(0.0, id="zero-float"),
        pytest.param("0", id="zero-string"),
        pytest.param(-0.0, id="negative-zero"),
        pytest.param(61.5, id="positive"),
        pytest.param(-33.8688, id="negative"),
        pytest.param(26, id="int"),
        pytest.param("61.5", id="numeric-string"),
        pytest.param("-151.2093", id="negative-numeric-string"),
        pytest.param(" 61.5 ", id="numeric-string-with-whitespace"),
    ],
)
def test_is_number_accepts_finite_numbers(value):
    assert _is_number(value) is True


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="none"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param("abc", id="text"),
        pytest.param("61,5", id="decimal-comma"),
        pytest.param([61.5], id="list"),
        pytest.param({"lat": 61.5}, id="dict"),
        *NON_FINITE_VALUES,
    ],
)
def test_is_number_rejects_missing_invalid_and_non_finite_values(value):
    assert _is_number(value) is False


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        pytest.param(0, 0, id="int-zero"),
        pytest.param(0.0, 0.0, id="float-zero"),
        pytest.param("0", "0", id="string-zero"),
        pytest.param(0, 26.1, id="zero-latitude"),
        pytest.param(61.7, 0, id="zero-longitude"),
    ],
)
def test_resolve_preserves_zero_coordinates(latitude, longitude):
    event = make_event(latitude=latitude, longitude=longitude, city="Lahti")

    result = resolve_event_location(event)

    assert result["locationStatus"] == "coordinates_available"
    assert result["needsGeocoding"] is False
    assert result["location"] == event["location"]


@pytest.mark.parametrize("bad_value", NON_FINITE_VALUES)
def test_resolve_non_finite_coordinates_fall_back_to_city(bad_value):
    result = resolve_event_location(make_event(latitude=bad_value, longitude=26.1, city="Lahti"))

    assert result["locationStatus"] == "city_resolved"
    assert (result["location"]["latitude"], result["location"]["longitude"]) == CITY_COORDINATES["Lahti"]


@pytest.mark.parametrize("bad_value", NON_FINITE_VALUES)
def test_resolve_non_finite_coordinates_without_city_need_geocoding(bad_value):
    result = resolve_event_location(make_event(latitude=61.7, longitude=bad_value))

    assert result["locationStatus"] == "needs_geocoding"
    assert result["needsGeocoding"] is True


def test_filter_includes_zero_coordinates():
    # (0, 0) is a valid coordinate; it is just far away from Joutsa.
    event = make_event(latitude=0, longitude=0)

    assert filter_near_joutsa([event]) == []
    assert len(filter_near_joutsa([event], radius_km=math.inf)) == 1


@pytest.mark.parametrize("bad_value", NON_FINITE_VALUES)
def test_filter_skips_non_finite_coordinates(bad_value):
    events = [
        make_event(latitude=bad_value, longitude=26.1),
        make_event(latitude=61.7, longitude=bad_value),
    ]

    assert filter_near_joutsa(events) == []


def test_filter_non_finite_coordinates_do_not_affect_valid_events():
    events = [
        make_event(city="Joutsa", latitude=61.7417, longitude=26.1142),
        make_event(city="Bad", latitude=math.inf, longitude=26.1),
        make_event(city="Lahti", latitude=60.9827, longitude=25.6615),
        make_event(city="Worse", latitude="nan", longitude="-inf"),
        make_event(city="Jyväskylä", latitude="62.2426", longitude="25.7473"),
    ]

    results = filter_near_joutsa(events)

    assert [event["location"]["city"] for event in results] == ["Joutsa", "Lahti", "Jyväskylä"]
    assert [event["distanceKm"] for event in results] == [0.1, 87.9, 58.8]


# --- Current behavior: known issues ------------------------------------------
# These tests document the existing implementation, including behavior that is
# probably wrong. They are intentionally explicit so that fixing any of these
# issues becomes a deliberate, visible test change.


def test_is_number_accepts_booleans():
    # Known issue: bool is a subclass of int, so True/False pass as 1.0/0.0.
    assert _is_number(True) is True
    assert _is_number(False) is True


@pytest.mark.parametrize(
    "location",
    [
        pytest.param("Helsinki", id="string"),
        pytest.param(["Lahti"], id="list"),
        pytest.param(42, id="number"),
    ],
)
def test_resolve_raises_for_non_empty_non_dict_location(location):
    # Known issue: only dicts and empty values are supported; other location
    # types still raise. filter_events_by_radius() has the same limitation
    # (it raises AttributeError for them).
    with pytest.raises(TypeError):
        resolve_event_location({"name": "Event", "location": location})
