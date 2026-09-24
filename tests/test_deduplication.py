import copy
import math

import pytest

from src.event_digest.deduplication import (
    deduplicate_events,
    distance_between,
    get_artist_name,
    get_coordinates,
    get_event_date,
    normalize,
)

EVENT_DATE = "2026-10-03"
BASE_LAT = 61.742667
BASE_LON = 26.112972

# Kilometers per degree of latitude with the 6371 km earth radius.
KM_PER_DEGREE_LATITUDE = 2 * math.pi * 6371 / 360


def make_event(
    name: str = "Artist",
    start_date: str | None = f"{EVENT_DATE}T19:00:00",
    url: str | None = None,
    **fields,
) -> dict:
    event = {"name": name, "startDate": start_date, **fields}
    if url is not None:
        event["url"] = url
    return event


def location_north_of_base(km: float, **fields) -> dict:
    return {
        "latitude": BASE_LAT + km / KM_PER_DEGREE_LATITUDE,
        "longitude": BASE_LON,
        **fields,
    }


def base_location(**fields) -> dict:
    return {"latitude": BASE_LAT, "longitude": BASE_LON, **fields}


# --- normalize / get_artist_name ---------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Artist", "artist"),
        ("  ARTIST  ", "artist"),
        ("Mötley Crüe", "motley crue"),
        ("Jyväskylä Sinfonia", "jyvaskyla sinfonia"),
        ("A&B!!", "a b"),
        ("Stand-up: Ismo", "stand up ismo"),
        ("Band   Name", "band name"),
        (123, "123"),
        (None, ""),
        ("", ""),
    ],
)
def test_normalize(value, expected):
    assert normalize(value) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        pytest.param("Artist", "artist", id="plain"),
        pytest.param("Artist @ Venue", "artist", id="at-venue-suffix"),
        pytest.param("Artist@Venue@City", "artist", id="multiple-at-signs"),
        pytest.param(
            "Artist - Venue - Joutsa - October 5, 2026",
            "artist",
            id="allevents-title-suffix",
        ),
        pytest.param(
            "Jean-Michel - Hall - Lahti - Oct 5, 2026",
            "jean michel",
            id="allevents-suffix-with-hyphenated-artist",
        ),
        pytest.param("Artist - Tour 2026", "artist tour 2026", id="short-suffix-kept"),
        pytest.param(None, "", id="none"),
        pytest.param("   ", "", id="whitespace"),
    ],
)
def test_get_artist_name(name, expected):
    assert get_artist_name(name) == expected


# --- get_event_date / get_coordinates / distance_between ----------------------


@pytest.mark.parametrize(
    ("start_date", "expected"),
    [
        ("2026-10-03", "2026-10-03"),
        ("2026-10-03T19:00:00", "2026-10-03"),
        ("2026-10-03T19:00:00+03:00", "2026-10-03"),
        (None, ""),
        ("", ""),
    ],
)
def test_get_event_date(start_date, expected):
    assert get_event_date({"startDate": start_date}) == expected


def test_get_event_date_missing_key():
    assert get_event_date({}) == ""


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        pytest.param({"latitude": 61.7, "longitude": 26.1}, {"lat": 61.7, "lon": 26.1}, id="floats"),
        pytest.param({"latitude": "61.7", "longitude": "26.1"}, {"lat": 61.7, "lon": 26.1}, id="strings"),
        pytest.param({"latitude": 0, "longitude": 0}, {"lat": 0.0, "lon": 0.0}, id="zero-is-valid"),
    ],
)
def test_get_coordinates_valid(location, expected):
    assert get_coordinates({"location": location}) == expected


@pytest.mark.parametrize(
    "event",
    [
        pytest.param({}, id="no-location"),
        pytest.param({"location": None}, id="none-location"),
        pytest.param({"location": {}}, id="empty-location"),
        pytest.param({"location": {"latitude": 61.7}}, id="latitude-only"),
        pytest.param({"location": {"latitude": "abc", "longitude": 26.1}}, id="non-numeric"),
        pytest.param({"location": {"latitude": math.nan, "longitude": 26.1}}, id="nan"),
        pytest.param({"location": {"latitude": 61.7, "longitude": math.inf}}, id="inf"),
        pytest.param({"location": {"latitude": "nan", "longitude": 26.1}}, id="nan-string"),
    ],
)
def test_get_coordinates_invalid_returns_none(event):
    assert get_coordinates(event) is None


def test_distance_between_same_point_is_zero():
    point = {"lat": BASE_LAT, "lon": BASE_LON}

    assert distance_between(point, point) == 0


def test_distance_between_one_degree_latitude():
    assert distance_between({"lat": 0, "lon": 0}, {"lat": 1, "lon": 0}) == pytest.approx(
        KM_PER_DEGREE_LATITUDE
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (None, {"lat": 0, "lon": 0}),
        ({"lat": 0, "lon": 0}, None),
        (None, None),
    ],
)
def test_distance_between_missing_point_is_infinite(first, second):
    assert distance_between(first, second) == math.inf


# --- deduplicate_events: empty and single inputs ------------------------------


def test_deduplicate_empty_list():
    assert deduplicate_events([]) == []


def test_deduplicate_single_event_adds_source_urls():
    event = make_event(url="https://a.example/event", location=base_location())

    assert deduplicate_events([event]) == [
        {**event, "sourceUrls": ["https://a.example/event"]}
    ]


def test_deduplicate_single_event_without_url_has_empty_source_urls():
    assert deduplicate_events([make_event()])[0]["sourceUrls"] == []


def test_deduplicate_single_event_keeps_existing_source_urls():
    event = make_event(url="https://c.example", sourceUrls=["https://a.example", "https://b.example"])

    result = deduplicate_events([event])

    assert result[0]["sourceUrls"] == [
        "https://a.example",
        "https://b.example",
        "https://c.example",
    ]


# --- deduplicate_events: matching ---------------------------------------------


@pytest.mark.parametrize(
    ("first_name", "second_name"),
    [
        pytest.param("Artist", "ARTIST", id="case"),
        pytest.param("Mötley Crüe", "Motley Crue", id="diacritics"),
        pytest.param("Artist!", "Artist", id="punctuation"),
        pytest.param("Artist", "Artist @ Joutsa Hall", id="at-venue"),
        pytest.param("Artist", "Artist - Hall - Joutsa - October 3, 2026", id="allevents-title"),
    ],
)
def test_deduplicate_merges_normalized_names_on_same_date(first_name, second_name):
    events = [
        make_event(first_name, url="https://a.example"),
        make_event(second_name, url="https://b.example"),
    ]

    result = deduplicate_events(events)

    assert len(result) == 1
    assert result[0]["sourceUrls"] == ["https://a.example", "https://b.example"]


def test_deduplicate_matches_on_date_regardless_of_time():
    events = [
        make_event(start_date=f"{EVENT_DATE}T14:00:00"),
        make_event(start_date=f"{EVENT_DATE}T20:00:00+03:00"),
    ]

    assert len(deduplicate_events(events)) == 1


def test_deduplicate_keeps_same_artist_on_different_dates():
    events = [
        make_event(start_date="2026-10-03T19:00:00"),
        make_event(start_date="2026-10-04T19:00:00"),
    ]

    assert len(deduplicate_events(events)) == 2


def test_deduplicate_keeps_different_artists_on_same_date():
    events = [make_event("Artist One"), make_event("Artist Two")]

    assert len(deduplicate_events(events)) == 2


# --- deduplicate_events: coordinate distance threshold -------------------------


@pytest.mark.parametrize("km", [0, 1, 4.9, 4.99])
def test_deduplicate_merges_when_within_five_km(km):
    events = [
        make_event(location=base_location()),
        make_event(location=location_north_of_base(km)),
    ]

    assert len(deduplicate_events(events)) == 1


@pytest.mark.parametrize("km", [5.01, 5.1, 50])
def test_deduplicate_keeps_separate_when_more_than_five_km_apart(km):
    events = [
        make_event(location=base_location()),
        make_event(location=location_north_of_base(km)),
    ]

    assert len(deduplicate_events(events)) == 2


@pytest.mark.parametrize(
    ("first_location", "second_location"),
    [
        pytest.param(base_location(), None, id="second-missing"),
        pytest.param(None, base_location(), id="first-missing"),
        pytest.param(None, None, id="both-missing"),
        pytest.param({"city": "Joutsa"}, {"city": "Lahti"}, id="cities-only"),
        pytest.param(
            base_location(),
            {"latitude": "abc", "longitude": BASE_LON},
            id="second-invalid",
        ),
    ],
)
def test_deduplicate_merges_when_either_side_lacks_coordinates(first_location, second_location):
    first = make_event(url="https://a.example")
    second = make_event(url="https://b.example")
    if first_location is not None:
        first["location"] = first_location
    if second_location is not None:
        second["location"] = second_location

    assert len(deduplicate_events([first, second])) == 1


# --- deduplicate_events: source URL merging ------------------------------------


def test_deduplicate_merges_source_urls_without_duplicates_in_order():
    events = [
        make_event(url="https://a.example"),
        make_event(url="https://b.example", sourceUrls=["https://a.example", "https://c.example"]),
        make_event(url="https://b.example"),
    ]

    result = deduplicate_events(events)

    assert result[0]["sourceUrls"] == [
        "https://a.example",
        "https://c.example",
        "https://b.example",
    ]


def test_deduplicate_drops_empty_urls_when_merging():
    events = [
        make_event(url="https://a.example"),
        make_event(url="", sourceUrls=["", None, "https://b.example"]),
    ]

    result = deduplicate_events(events)

    assert result[0]["sourceUrls"] == ["https://a.example", "https://b.example"]


def test_deduplicate_keeps_first_event_url_field():
    events = [
        make_event(url="https://a.example"),
        make_event(url="https://b.example"),
    ]

    assert deduplicate_events(events)[0]["url"] == "https://a.example"


# --- deduplicate_events: field merging and completeness ------------------------


def test_deduplicate_prefers_longer_name():
    events = [
        make_event("Artist"),
        make_event("Artist @ Joutsa Hall"),
        make_event("ARTIST"),
    ]

    assert deduplicate_events(events)[0]["name"] == "Artist @ Joutsa Hall"


def test_deduplicate_fills_missing_description_but_keeps_existing_one():
    events = [
        make_event(),
        make_event(description="First description"),
        make_event(description="Second, much longer description"),
    ]

    assert deduplicate_events(events)[0]["description"] == "First description"


def test_deduplicate_takes_coordinates_and_distance_from_duplicate():
    events = [
        make_event(location={"city": "Joutsa"}),
        make_event(location=base_location(venue="Hall"), distanceKm=0.0),
    ]

    result = deduplicate_events(events)[0]

    assert result["location"] == base_location(city="Joutsa", venue="Hall")
    assert result["distanceKm"] == 0.0


def test_deduplicate_existing_coordinates_win_over_duplicate():
    events = [
        make_event(location=base_location()),
        make_event(location=location_north_of_base(1)),
    ]

    result = deduplicate_events(events)[0]

    assert result["location"]["latitude"] == BASE_LAT


def test_deduplicate_fills_missing_location_fields():
    events = [
        make_event(location=base_location(venue="Hall")),
        make_event(location={"venue": "Other hall", "city": "Joutsa", "address": "Street 1"}),
    ]

    result = deduplicate_events(events)[0]

    assert result["location"]["venue"] == "Hall"
    assert result["location"]["city"] == "Joutsa"
    assert result["location"]["address"] == "Street 1"


@pytest.mark.parametrize("empty_value", ["", None])
def test_deduplicate_replaces_empty_location_fields(empty_value):
    events = [
        make_event(location={"venue": empty_value, "city": empty_value, "address": empty_value}),
        make_event(location={"venue": "Hall", "city": "Joutsa", "address": "Street 1"}),
    ]

    result = deduplicate_events(events)[0]

    assert result["location"] == {"venue": "Hall", "city": "Joutsa", "address": "Street 1"}


def test_deduplicate_fills_missing_distance():
    events = [
        make_event(location={"city": "Joutsa"}),
        make_event(location={"city": "Joutsa"}, distanceKm=2.5),
    ]

    assert deduplicate_events(events)[0]["distanceKm"] == 2.5


def test_deduplicate_keeps_first_event_other_fields():
    events = [
        make_event(image="first.jpg", start_date=f"{EVENT_DATE}T18:00:00"),
        make_event(image="second.jpg", organizer="Org", start_date=f"{EVENT_DATE}T20:00:00"),
    ]

    result = deduplicate_events(events)[0]

    assert result["image"] == "first.jpg"
    assert result["startDate"] == f"{EVENT_DATE}T18:00:00"
    assert "organizer" not in result


# --- deduplicate_events: multiple duplicates -----------------------------------


def test_deduplicate_merges_many_duplicates_into_one_group():
    events = [make_event(url=f"https://{index}.example") for index in range(5)]

    result = deduplicate_events(events)

    assert len(result) == 1
    assert result[0]["sourceUrls"] == [f"https://{index}.example" for index in range(5)]


def test_deduplicate_mixed_input_preserves_first_appearance_order():
    events = [
        make_event("Band A", url="https://a1.example"),
        make_event("Band B", url="https://b1.example"),
        make_event("band a", url="https://a2.example"),
        make_event("Band C", url="https://c1.example"),
        make_event("Band B!", url="https://b2.example"),
        make_event("Band A", start_date="2026-10-10", url="https://a3.example"),
    ]

    result = deduplicate_events(events)

    assert [event["sourceUrls"] for event in result] == [
        ["https://a1.example", "https://a2.example"],
        ["https://b1.example", "https://b2.example"],
        ["https://c1.example"],
        ["https://a3.example"],
    ]


def test_deduplicate_event_without_coordinates_joins_first_matching_group():
    events = [
        make_event(url="https://near.example", location=base_location()),
        make_event(url="https://far.example", location=location_north_of_base(50)),
        make_event(url="https://unknown.example"),
    ]

    result = deduplicate_events(events)

    assert [event["sourceUrls"] for event in result] == [
        ["https://near.example", "https://unknown.example"],
        ["https://far.example"],
    ]


# --- deduplicate_events: events that cannot be matched --------------------------


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(make_event(name=""), id="empty-name"),
        pytest.param(make_event(name=None), id="none-name"),
        pytest.param(make_event(name="@home"), id="name-empty-after-at-split"),
        pytest.param(make_event(start_date=None), id="no-start-date"),
        pytest.param(make_event(start_date=""), id="empty-start-date"),
    ],
)
def test_deduplicate_never_merges_events_without_artist_or_date(event):
    events = [copy.deepcopy(event), copy.deepcopy(event)]

    assert len(deduplicate_events(events)) == 2


# --- deduplicate_events: immutability ------------------------------------------


def test_deduplicate_does_not_mutate_input():
    events = [
        make_event(url="https://a.example", location={"city": "Joutsa", "venue": ""}),
        make_event(
            "Artist @ Hall",
            url="https://b.example",
            sourceUrls=["https://c.example"],
            description="Description",
            location=base_location(venue="Hall", address="Street 1"),
            distanceKm=0.0,
        ),
        make_event(name="", url="https://d.example"),
    ]
    original = copy.deepcopy(events)

    result = deduplicate_events(events)

    assert events == original
    assert all(group is not event for group in result for event in events)


# --- deduplicate_events: location None --------------------------------------
# "location": None is valid input (see the Event model) and is treated like a
# missing location: no coordinates, so distance cannot be compared.


def test_deduplicate_merges_duplicates_with_none_locations():
    events = [
        make_event(url="https://a.example", location=None, description="First"),
        make_event(url="https://b.example", location=None),
    ]

    result = deduplicate_events(events)

    assert len(result) == 1
    assert result[0]["sourceUrls"] == ["https://a.example", "https://b.example"]
    assert result[0]["description"] == "First"


def test_deduplicate_none_locations_behave_like_missing_locations():
    with_none = [make_event(url="https://a.example", location=None), make_event(url="https://b.example", location=None)]
    missing = [make_event(url="https://a.example"), make_event(url="https://b.example")]

    assert deduplicate_events(with_none) == deduplicate_events(missing)


def test_deduplicate_none_location_duplicate_keeps_group_location():
    events = [
        make_event(url="https://a.example", location=base_location(venue="Hall", city="Joutsa")),
        make_event(url="https://b.example", location=None),
    ]

    [result] = deduplicate_events(events)

    assert result["location"] == base_location(venue="Hall", city="Joutsa")
    assert result["sourceUrls"] == ["https://a.example", "https://b.example"]


def test_deduplicate_none_location_group_takes_duplicate_location():
    events = [
        make_event(url="https://a.example", location=None),
        make_event(url="https://b.example", location=base_location(venue="Hall"), distanceKm=0.1),
    ]

    [result] = deduplicate_events(events)

    assert result["location"] == base_location(venue="Hall")
    assert result["distanceKm"] == 0.1


def test_deduplicate_many_missing_or_none_locations():
    events = [
        make_event(url="https://1.example", location=None),
        make_event(url="https://2.example"),
        make_event(url="https://3.example", location=None),
        make_event(url="https://4.example", location={}),
        make_event("Other artist", url="https://5.example", location=None),
    ]

    result = deduplicate_events(events)

    assert [group["sourceUrls"] for group in result] == [
        ["https://1.example", "https://2.example", "https://3.example", "https://4.example"],
        ["https://5.example"],
    ]


def test_deduplicate_none_location_does_not_change_coordinate_matching():
    # Same as test_deduplicate_event_without_coordinates_joins_first_matching_group,
    # with an explicit None location.
    events = [
        make_event(url="https://near.example", location=base_location()),
        make_event(url="https://far.example", location=location_north_of_base(50)),
        make_event(url="https://unknown.example", location=None),
    ]

    result = deduplicate_events(events)

    assert [group["sourceUrls"] for group in result] == [
        ["https://near.example", "https://unknown.example"],
        ["https://far.example"],
    ]


def test_deduplicate_single_none_location_event_is_unchanged():
    event = make_event(url="https://a.example", location=None)

    assert deduplicate_events([event]) == [{**event, "sourceUrls": ["https://a.example"]}]


def test_deduplicate_none_location_does_not_mutate_input():
    events = [make_event(location=base_location()), make_event(location=None)]
    original = copy.deepcopy(events)

    deduplicate_events(events)

    assert events == original


# --- Current behavior: known issues ------------------------------------------
# These tests document the existing implementation, including behavior that is
# probably wrong. They are intentionally explicit so that fixing any of these
# issues becomes a deliberate, visible test change.


def test_new_group_source_urls_are_not_deduplicated():
    # Known issue: only merge_event() deduplicates URLs.
    event = make_event(url="https://a.example", sourceUrls=["https://a.example", "https://b.example"])

    assert deduplicate_events([event])[0]["sourceUrls"] == [
        "https://a.example",
        "https://b.example",
        "https://a.example",
    ]


def test_unmatchable_event_drops_existing_source_urls():
    # Known issue: events without artist/date ignore their incoming sourceUrls.
    event = make_event(name="", url="https://a.example", sourceUrls=["https://b.example"])

    assert deduplicate_events([event])[0]["sourceUrls"] == ["https://a.example"]


def test_merge_with_coordinates_but_no_distance_clears_existing_distance():
    # Known issue: taking coordinates from a duplicate overwrites distanceKm
    # even when the duplicate has no distanceKm.
    events = [
        make_event(distanceKm=3.0),
        make_event(location=base_location()),
    ]

    assert deduplicate_events(events)[0]["distanceKm"] is None


def test_non_string_start_date_raises():
    # Known issue: startDate is sliced without a type check.
    with pytest.raises(TypeError):
        deduplicate_events([make_event(start_date=20261003)])


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # Known issue: non-Latin letters are removed entirely, so these events
        # get an empty artist key and are never deduplicated.
        ("Кино", ""),
        # Known issue: letters without a decomposed form (ø) are split out.
        ("Røyksopp", "r yksopp"),
    ],
)
def test_artist_name_drops_non_latin_characters(name, expected):
    assert get_artist_name(name) == expected


def test_non_latin_duplicates_are_not_merged():
    events = [make_event("Кино"), make_event("Кино")]

    assert len(deduplicate_events(events)) == 2


def test_same_artist_same_day_different_times_collapse():
    # Known issue (design): matinee and evening shows are merged into one
    # event; only the first startDate is kept.
    events = [
        make_event(start_date=f"{EVENT_DATE}T14:00:00", url="https://matinee.example"),
        make_event(start_date=f"{EVENT_DATE}T19:00:00", url="https://evening.example"),
    ]

    result = deduplicate_events(events)

    assert len(result) == 1
    assert result[0]["startDate"] == f"{EVENT_DATE}T14:00:00"


def test_matching_depends_on_input_order():
    # Known issue: a group can gain coordinates from a merged duplicate, which
    # changes how later events match it.
    unknown = make_event(url="https://unknown.example")
    near = make_event(url="https://near.example", location=base_location())
    far = make_event(url="https://far.example", location=location_north_of_base(50))

    unknown_first = deduplicate_events([unknown, near, far])
    far_first = deduplicate_events([far, unknown, near])

    # The same three events: "unknown" ends up grouped with whichever located
    # event it meets first.
    assert [group["sourceUrls"] for group in unknown_first] == [
        ["https://unknown.example", "https://near.example"],
        ["https://far.example"],
    ]
    assert [group["sourceUrls"] for group in far_first] == [
        ["https://far.example", "https://unknown.example"],
        ["https://near.example"],
    ]
