import copy
import json
import math
from pathlib import Path

import pytest

from src.event_digest.extraction import (
    _parse_coordinate,
    clean_text,
    collect_jsonld_events,
    decode,
    extract_allevents,
    extract_event_data,
    extract_jsonld,
    extract_time,
    get_field,
    get_jsonld_time,
    is_event_type,
    iter_allevents_records,
    normalize_date,
    parse_allevents_display_date,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PAGE_PATH = PROJECT_ROOT / "config" / "test-event-page.html"

PAGE_URL = "https://www.jambase.com/concerts/fi"
EVENT_URL = "https://www.jambase.com/show/neelix-apollo-live-club-20261003"


# --- Fixtures: JSON-LD -------------------------------------------------------
# Modeled on the JamBase MusicEvent blocks in config/test-event-page.html.

MUSIC_EVENT = {
    "@context": "http://schema.org",
    "@type": "MusicEvent",
    "eventStatus": "http://schema.org/EventScheduled",
    "name": "Neelix - Helsinki - Apollo Live Club - Oct 3, 2026",
    "description": "Neelix at Apollo Live Club on Oct 3, 2026",
    "url": EVENT_URL,
    "startDate": "2026-10-03T23:00:00",
    "endDate": "2026-10-04",
    "location": {
        "@type": "Place",
        "name": "Apollo Live Club",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": "Mannerheimintie 16",
            "addressLocality": "Helsinki",
            "postalCode": "100",
            "addressRegion": None,
            "addressCountry": "FI",
        },
        "geo": {
            "@type": "GeoCoordinates",
            "latitude": "60.1688",
            "longitude": "24.9398",
        },
    },
    "performer": [{"@type": "MusicGroup", "name": "Neelix"}],
    "offers": {"@type": "Offer", "price": "25.00", "priceCurrency": "EUR"},
}

EXPECTED_MUSIC_EVENT = {
    "name": "Neelix - Helsinki - Apollo Live Club - Oct 3, 2026",
    "startDate": "2026-10-03",
    "endDate": "2026-10-04",
    "time": "23:00",
    "price": "25.00",
    "location": {
        "venue": "Apollo Live Club",
        "city": "Helsinki",
        "address": "Mannerheimintie 16",
        "latitude": 60.1688,
        "longitude": 24.9398,
    },
    "description": "Neelix at Apollo Live Club on Oct 3, 2026",
    "url": EVENT_URL,
    "sourceUrls": [EVENT_URL],
    "sourceType": "jsonld",
}


def music_event(**overrides) -> dict:
    event = copy.deepcopy(MUSIC_EVENT)
    event.update(overrides)
    return event


def minimal_event(name: str = "Event", start_date: str = "2026-10-03", **fields) -> dict:
    return {"@type": "Event", "name": name, "startDate": start_date, **fields}


def jsonld_script(data, attributes: str = 'type="application/ld+json"') -> str:
    return f"<script {attributes}>\n{json.dumps(data, indent=2)}\n</script>"


def html_page(*body_parts: str) -> str:
    body = "\n".join(body_parts)
    return (
        "<!DOCTYPE html><html lang=\"en-US\"><head><meta charset=\"utf-8\">"
        "<title>Concerts</title></head>"
        f"<body>{body}</body></html>"
    )


def jsonld_page(*data) -> str:
    return html_page(*(jsonld_script(item) for item in data))


def extract_single(data, page_url: str | None = PAGE_URL) -> dict:
    results = extract_jsonld(jsonld_page(data), page_url)
    assert len(results) == 1
    return results[0]


# --- Fixtures: Allevents -----------------------------------------------------

ALLEVENTS_URL = "https://allevents.in/joutsa/stand-up-ismo-leikola/3200012345"
ALLEVENTS_LISTING_URL = "https://allevents.in/joutsa/comedy"

ALLEVENTS_JYVASKYLA_PATH = PROJECT_ROOT / "tests" / "fixtures" / "allevents-jyvaskyla-music.html"
ALLEVENTS_JYVASKYLA_URL = "https://allevents.in/jyv%c3%a4skyl%c3%a4/music"
ALLEVENTS_ULVERSTONE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "allevents-ulverstone-live-music.html"

# Top-level record fields; everything else lives in the nested "venue" object,
# matching real Allevents listing pages (see tests/fixtures/allevents-*.html).
ALLEVENTS_FIELDS = {
    "event_id": "3200012345",
    "eventname": "Stand-up: Ismo Leikola",
    "start_time_display": "Sat Oct 3 2026 at 07:00 pm",
    "location": "Joutsa-talo",
    "event_url": ALLEVENTS_URL,
    "short_description": "Stand-up evening in Jyväskylä & Joutsa.",
}

ALLEVENTS_VENUE_FIELDS = {
    "street": "Jousitie 1",
    "city": "Joutsa",
    "country": "Finland",
    "latitude": "61.7417",
    "longitude": "26.1142",
    "full_address": "Jousitie 1, 19650 Joutsa, Finland",
}


def allevents_record(**overrides) -> dict:
    """Build one Allevents record in the real listing-page structure.

    Overrides for venue fields are applied to the nested "venue" object.
    An override of None removes the field.
    """

    record = dict(ALLEVENTS_FIELDS)
    venue = dict(ALLEVENTS_VENUE_FIELDS)

    for key, value in overrides.items():
        target = venue if key in ALLEVENTS_VENUE_FIELDS else record
        target[key] = value

    record = {key: value for key, value in record.items() if value is not None}
    record["venue"] = {key: value for key, value in venue.items() if value is not None}
    return record


def allevents_page(*records: dict) -> str:
    """Embed records the way Allevents listing pages do."""

    return html_page(
        "<script>",
        "var _this = this;",
        "_this.events_data = [];",
        f"_this.events_data = {json.dumps(records)};",
        "_this.events_data_with_ads = [];",
        "</script>",
    )


def extract_single_allevents(page_url: str | None = ALLEVENTS_LISTING_URL, **overrides) -> dict:
    results = extract_allevents(allevents_page(allevents_record(**overrides)), page_url)
    assert len(results) == 1
    return results[0]


@pytest.fixture(scope="module")
def sample_page_html() -> str:
    return SAMPLE_PAGE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def allevents_finnish_page() -> str:
    return ALLEVENTS_JYVASKYLA_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def allevents_foreign_page() -> str:
    return ALLEVENTS_ULVERSTONE_PATH.read_text(encoding="utf-8")


# --- decode ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(None, None, id="none"),
        pytest.param("plain text", "plain text", id="plain"),
        pytest.param(r"Jyväskylä", "Jyväskylä", id="unicode-escape"),
        pytest.param(r"ÄÄNEKOSKI", "ÄÄNEKOSKI", id="uppercase-hex"),
        pytest.param(r"https:\/\/allevents.in\/joutsa", "https://allevents.in/joutsa", id="escaped-slash"),
        pytest.param(r"Say \"hi\"", 'Say "hi"', id="escaped-quote"),
        pytest.param("Rock &amp; Roll", "Rock & Roll", id="amp-entity"),
        pytest.param(123, "123", id="non-string"),
        pytest.param("", "", id="empty"),
    ],
)
def test_decode(value, expected):
    assert decode(value) == expected


# --- clean_text --------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(None, None, id="none"),
        pytest.param("  Apollo   Live\n\tClub  ", "Apollo Live Club", id="whitespace"),
        pytest.param("Joutsa", "Joutsa", id="unchanged"),
        pytest.param("", "", id="empty"),
        pytest.param("   \n ", "", id="only-whitespace"),
        pytest.param(25.5, "25.5", id="non-string"),
    ],
)
def test_clean_text(value, expected):
    assert clean_text(value) == expected


# --- get_field ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "field", "expected"),
    [
        pytest.param('{"city":"Joutsa"}', "city", "Joutsa", id="basic"),
        pytest.param('{"city" :  "Joutsa"}', "city", "Joutsa", id="whitespace-around-colon"),
        pytest.param(r'{"name":"Say \"hi\""}', "name", 'Say "hi"', id="escaped-quote-in-value"),
        pytest.param(r'{"city":"Jyväskylä"}', "city", "Jyväskylä", id="unicode-in-value"),
        pytest.param('{"city":""}', "city", "", id="empty-value"),
        pytest.param('{"city":"First"} {"city":"Second"}', "city", "First", id="first-occurrence"),
        pytest.param('{"country":"Finland"}', "city", None, id="missing"),
        pytest.param(
            '{"short_description":"Short"}',
            "description",
            None,
            id="does-not-match-suffix-field",
        ),
        pytest.param('{"a.b":"dotted", "aXb":"other"}', "a.b", "dotted", id="field-name-escaped"),
    ],
)
def test_get_field(raw, field, expected):
    assert get_field(raw, field) == expected


# --- _parse_coordinate -------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("61.7417", 61.7417, id="string"),
        pytest.param(" 61.7417 ", 61.7417, id="string-with-whitespace"),
        pytest.param("-33.8688", -33.8688, id="negative"),
        pytest.param(26.1142, 26.1142, id="float"),
        pytest.param(26, 26.0, id="int"),
        pytest.param(0, 0.0, id="zero"),
        pytest.param("0", 0.0, id="zero-string"),
    ],
)
def test_parse_coordinate_valid(value, expected):
    result = _parse_coordinate(value)

    assert result == expected
    assert isinstance(result, float)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="none"),
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param("61,7417", id="decimal-comma"),
        pytest.param("61.7417N", id="suffix"),
        pytest.param("unknown", id="text"),
        pytest.param({"value": 61.7}, id="dict"),
        pytest.param([61.7], id="list"),
    ],
)
def test_parse_coordinate_missing_or_malformed_is_none(value):
    assert _parse_coordinate(value) is None


# --- normalize_date ----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-03", "2026-10-03"),
        ("2026-10-03T19:00:00", "2026-10-03"),
        ("2026-10-03T19:00:00+03:00", "2026-10-03"),
        ("2026-10-03 19:00", "2026-10-03"),
        (None, None),
        ("", None),
        ("3.10.2026", None),
        ("Oct 3, 2026", None),
        ("26-10-03", None),
        (" 2026-10-03", None),
        (20261003, None),
    ],
)
def test_normalize_date(value, expected):
    assert normalize_date(value) == expected


# --- extract_time ------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("07:00 pm", "19:00", id="pm"),
        pytest.param("09:00 PM", "21:00", id="uppercase-pm"),
        pytest.param("9:30am", "09:30", id="am-no-space"),
        pytest.param("12:00 am", "00:00", id="midnight"),
        pytest.param("12:30 pm", "12:30", id="noon"),
        pytest.param("Sat Oct 3 2026 at 07:00 pm", "19:00", id="allevents-display"),
    ],
)
def test_extract_time_12_hour(value, expected):
    assert extract_time(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("19:00", "19:00", id="plain"),
        pytest.param("9:05", "09:05", id="single-digit-hour"),
        pytest.param("00:00", "00:00", id="midnight"),
        pytest.param("23:59", "23:59", id="last-minute"),
        pytest.param("2026-10-03T19:00:00", "19:00", id="iso-datetime"),
        pytest.param("2026-10-03T19:30:00+03:00", "19:30", id="iso-with-offset"),
        pytest.param("Doors open 18:30, show 20:00", "18:30", id="first-time-wins"),
        pytest.param("24:00", None, id="hour-24-rejected"),
        pytest.param("19:60", None, id="minute-60-rejected"),
        pytest.param("119:00", None, id="three-digit-hour-rejected"),
    ],
)
def test_extract_time_24_hour(value, expected):
    assert extract_time(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("klo 19.30", "19:30", id="klo"),
        pytest.param("KLO 19.30", "19:30", id="uppercase"),
        pytest.param("kl. 19.30", "19:30", id="kl-dot"),
        pytest.param("kl 19.30", "19:30", id="kl"),
        pytest.param("klo19.30", "19:30", id="no-space"),
        pytest.param("Lauantaina 3.10. klo 18.00 alkaen", "18:00", id="in-sentence"),
        pytest.param("klo 19:30", "19:30", id="colon-uses-24-hour-rule"),
    ],
)
def test_extract_time_finnish(value, expected):
    assert extract_time(value) == expected


@pytest.mark.parametrize(
    "value",
    [None, "", "2026-10-03", "Free entry", "Ages 18+", 0],
)
def test_extract_time_returns_none_without_time(value):
    assert extract_time(value) is None


def test_extract_time_prefers_12_hour_anywhere_in_text():
    assert extract_time("Doors 18:00, show 8:00 pm") == "20:00"


# --- parse_allevents_display_date --------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Sat Oct 3 2026 at 07:00 pm", "2026-10-03"),
        ("Sun Oct 18 2026", "2026-10-18"),
        ("SAT OCT 3 2026", "2026-10-03"),
        ("Thu Jan 1 2026", "2026-01-01"),
        ("Thu Dec 31 2026", "2026-12-31"),
        (None, None),
        ("", None),
        ("Saturday October 3 2026", None),
        ("Oct 3 2026", None),
        ("Sat Foo 3 2026", None),
        ("Sat 3 Oct 2026", None),
        ("On Sat Oct 3 2026", None),
    ],
)
def test_parse_allevents_display_date(value, expected):
    assert parse_allevents_display_date(value) == expected


@pytest.mark.parametrize(
    ("month", "number"),
    [
        ("Jan", "01"), ("Feb", "02"), ("Mar", "03"), ("Apr", "04"),
        ("May", "05"), ("Jun", "06"), ("Jul", "07"), ("Aug", "08"),
        ("Sep", "09"), ("Oct", "10"), ("Nov", "11"), ("Dec", "12"),
    ],
)
def test_parse_allevents_display_date_all_months(month, number):
    assert parse_allevents_display_date(f"Mon {month} 5 2026") == f"2026-{number}-05"


# --- is_event_type -----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Event", True),
        ("MusicEvent", True),
        ("ComedyEvent", True),
        ("TheaterEvent", True),
        ("event", True),
        ("http://schema.org/Event", True),
        (["Thing", "MusicEvent"], True),
        (["Place", "Organization"], False),
        ([None, 1, "Event"], True),
        ([None, 1], False),
        ([], False),
        ("Place", False),
        ("EventSeries", False),
        ("Eventful", False),
        ("", False),
        (None, False),
        ({"@type": "Event"}, False),
    ],
)
def test_is_event_type(value, expected):
    assert is_event_type(value) is expected


# --- get_jsonld_time ---------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        pytest.param(
            {"startDate": "2026-10-03T19:00:00", "description": "klo 20.00"},
            "19:00",
            id="start-date-time-wins",
        ),
        pytest.param(
            {"startDate": "2026-10-03", "description": "Ovet klo 18.30"},
            "18:30",
            id="date-only-falls-back-to-description",
        ),
        pytest.param(
            {"startDate": "2026-10-03T00:00:00", "description": "Show at 8:00 pm"},
            "20:00",
            id="midnight-falls-back-to-description",
        ),
        pytest.param(
            {"startDate": "2026-10-03T00:00:00", "description": "No time here"},
            "00:00",
            id="midnight-kept-without-description-time",
        ),
        pytest.param(
            {"startTime": "19:30"},
            "19:30",
            id="start-time-fallback",
        ),
        pytest.param({"startDate": "2026-10-03"}, None, id="no-time"),
        pytest.param({}, None, id="empty"),
    ],
)
def test_get_jsonld_time(event, expected):
    assert get_jsonld_time(event) == expected


# --- collect_jsonld_events ---------------------------------------------------


def names(events: list[dict]) -> list[str]:
    return [event["name"] for event in events]


def test_collect_single_event():
    assert names(collect_jsonld_events(minimal_event("A"), [])) == ["A"]


def test_collect_from_list_in_order():
    data = [minimal_event("A"), {"@type": "Place", "name": "P"}, minimal_event("B")]

    assert names(collect_jsonld_events(data, [])) == ["A", "B"]


def test_collect_from_graph():
    data = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebPage", "name": "Concerts"},
            minimal_event("A"),
            {"@type": "BreadcrumbList", "name": "Crumbs"},
        ],
    }

    assert names(collect_jsonld_events(data, [])) == ["A"]


@pytest.mark.parametrize(
    "nested",
    [
        pytest.param(minimal_event("A"), id="single"),
        pytest.param([minimal_event("A")], id="list"),
    ],
)
def test_collect_from_event_property(nested):
    data = {"@type": "Place", "name": "Apollo Live Club", "event": nested}

    assert names(collect_jsonld_events(data, [])) == ["A"]


def test_collect_includes_parent_and_sub_events():
    data = minimal_event("Festival", event=[minimal_event("Day 1"), minimal_event("Day 2")])

    assert names(collect_jsonld_events(data, [])) == ["Festival", "Day 1", "Day 2"]


def test_collect_deeply_nested():
    data = {"@graph": [{"@type": "Place", "event": {"@graph": [minimal_event("Deep")]}}]}

    assert names(collect_jsonld_events(data, [])) == ["Deep"]


def test_collect_ignores_non_list_graph():
    data = {"@graph": minimal_event("Hidden")}

    assert collect_jsonld_events(data, []) == []


@pytest.mark.parametrize("value", [None, {}, [], "", "Event", 42, [None, "text", 1]])
def test_collect_ignores_empty_and_non_object_values(value):
    assert collect_jsonld_events(value, []) == []


def test_collect_appends_to_given_result_list():
    result = [{"name": "existing"}]

    returned = collect_jsonld_events(minimal_event("A"), result)

    assert returned is result
    assert names(result) == ["existing", "A"]


# --- extract_jsonld: full mapping --------------------------------------------


def test_extract_jsonld_maps_realistic_music_event():
    assert extract_single(MUSIC_EVENT) == EXPECTED_MUSIC_EVENT


def test_extract_jsonld_handles_escaped_slashes_in_raw_json():
    raw = (
        '<script type="application/ld+json">{"@type":"MusicEvent","name":"Neelix",'
        '"startDate":"2026-10-03","url":"https:\\/\\/www.jambase.com\\/show\\/neelix"}</script>'
    )

    assert extract_jsonld(raw, PAGE_URL)[0]["url"] == "https://www.jambase.com/show/neelix"


def test_extract_jsonld_from_multiple_scripts_and_lists():
    html = jsonld_page(
        {"@type": "WebSite", "name": "JamBase"},
        [minimal_event("A"), minimal_event("B")],
        {"@graph": [minimal_event("C")]},
    )

    assert names(extract_jsonld(html, PAGE_URL)) == ["A", "B", "C"]


@pytest.mark.parametrize(
    "attributes",
    [
        pytest.param('type="application/ld+json"', id="double-quotes"),
        pytest.param("type='application/ld+json'", id="single-quotes"),
        pytest.param('TYPE="Application/LD+JSON"', id="uppercase"),
        pytest.param('id="schema" type="application/ld+json" nonce="abc"', id="extra-attributes"),
    ],
)
def test_extract_jsonld_script_tag_variants(attributes):
    html = html_page(jsonld_script(minimal_event("A"), attributes=attributes))

    assert names(extract_jsonld(html, PAGE_URL)) == ["A"]


def test_extract_jsonld_ignores_other_scripts():
    html = html_page(
        '<script type="text/javascript">var event = {"@type": "Event"};</script>',
        '<script type="application/json">{"@type":"Event","name":"A","startDate":"2026-10-03"}</script>',
    )

    assert extract_jsonld(html, PAGE_URL) == []


@pytest.mark.parametrize(
    "html",
    [
        pytest.param("", id="empty-html"),
        pytest.param(html_page("<p>No structured data</p>"), id="no-scripts"),
        pytest.param(html_page('<script type="application/ld+json">   </script>'), id="empty-script"),
    ],
)
def test_extract_jsonld_returns_empty_without_events(html):
    assert extract_jsonld(html, PAGE_URL) == []


# --- extract_jsonld: malformed data ------------------------------------------


@pytest.mark.parametrize(
    "raw_json",
    [
        pytest.param('{"@type": "Event", "name": "Broken",', id="truncated"),
        pytest.param("{'@type': 'Event'}", id="single-quoted-keys"),
        pytest.param("not json at all", id="text"),
    ],
)
def test_extract_jsonld_skips_invalid_json_and_keeps_valid_blocks(raw_json):
    html = html_page(
        jsonld_script(minimal_event("Before")),
        f'<script type="application/ld+json">{raw_json}</script>',
        jsonld_script(minimal_event("After")),
    )

    assert names(extract_jsonld(html, PAGE_URL)) == ["Before", "After"]


@pytest.mark.parametrize(
    "event",
    [
        pytest.param({"@type": "Event", "startDate": "2026-10-03"}, id="missing-name"),
        pytest.param(minimal_event(name="   "), id="blank-name"),
        pytest.param({"@type": "Event", "name": "A"}, id="missing-start-date"),
        pytest.param(minimal_event(start_date="3.10.2026"), id="non-iso-start-date"),
        pytest.param(minimal_event(start_date=""), id="empty-start-date"),
        pytest.param({"@type": "Place", "name": "A", "startDate": "2026-10-03"}, id="not-an-event"),
    ],
)
def test_extract_jsonld_skips_events_without_name_or_valid_start_date(event):
    assert extract_jsonld(jsonld_page(event), PAGE_URL) == []


# --- extract_jsonld: individual fields ---------------------------------------


def test_extract_jsonld_cleans_name_and_description_whitespace():
    event = minimal_event(name="  Neelix \n live  ", description="Line one\n\n   line two")

    result = extract_single(event)

    assert result["name"] == "Neelix live"
    assert result["description"] == "Line one line two"


def test_extract_jsonld_missing_description_is_none():
    assert extract_single(minimal_event())["description"] is None


def test_extract_jsonld_end_date_defaults_to_start_date():
    result = extract_single(minimal_event(start_date="2026-10-03T19:00:00"))

    assert result["endDate"] == "2026-10-03"


def test_extract_jsonld_invalid_end_date_defaults_to_start_date():
    result = extract_single(minimal_event(endDate="soon"))

    assert result["endDate"] == "2026-10-03"


@pytest.mark.parametrize(
    ("event_url", "page_url", "expected_url", "expected_sources"),
    [
        pytest.param(EVENT_URL, PAGE_URL, EVENT_URL, [EVENT_URL], id="event-url"),
        pytest.param(None, PAGE_URL, PAGE_URL, [PAGE_URL], id="page-url-fallback"),
        pytest.param("", PAGE_URL, PAGE_URL, [PAGE_URL], id="empty-event-url"),
        pytest.param(None, None, None, [], id="no-url"),
    ],
)
def test_extract_jsonld_urls(event_url, page_url, expected_url, expected_sources):
    event = minimal_event()
    if event_url is not None:
        event["url"] = event_url

    result = extract_single(event, page_url=page_url)

    assert result["url"] == expected_url
    assert result["sourceUrls"] == expected_sources


@pytest.mark.parametrize(
    ("offers", "expected"),
    [
        pytest.param({"price": "25.00"}, "25.00", id="string-price"),
        pytest.param({"price": 15}, 15, id="numeric-price"),
        pytest.param({"price": 0}, 0, id="free"),
        pytest.param({"priceCurrency": "EUR"}, None, id="no-price"),
        pytest.param("25 EUR", None, id="string-offers"),
    ],
)
def test_extract_jsonld_price(offers, expected):
    assert extract_single(minimal_event(offers=offers))["price"] == expected


def test_extract_jsonld_missing_offers_price_is_none():
    assert extract_single(minimal_event())["price"] is None


def test_extract_jsonld_location_city_from_location_when_no_address_object():
    event = minimal_event(location={"name": "Joutsa-talo", "addressLocality": "Joutsa"})

    assert extract_single(event)["location"] == {
        "venue": "Joutsa-talo",
        "city": "Joutsa",
        "address": None,
        "latitude": None,
        "longitude": None,
    }


def test_extract_jsonld_address_locality_prefers_address_object():
    event = minimal_event(
        location={
            "addressLocality": "Wrong",
            "address": {"addressLocality": "  Joutsa ", "streetAddress": " Jousitie   1 "},
        }
    )

    location = extract_single(event)["location"]

    assert location["city"] == "Joutsa"
    assert location["address"] == "Jousitie 1"


@pytest.mark.parametrize(
    "location",
    [
        pytest.param(None, id="missing"),
        pytest.param("Apollo Live Club, Helsinki", id="string"),
        pytest.param(["Apollo Live Club"], id="list"),
        pytest.param({}, id="empty-object"),
    ],
)
def test_extract_jsonld_unusable_location_gives_empty_fields(location):
    event = minimal_event()
    if location is not None:
        event["location"] = location

    assert extract_single(event)["location"] == {
        "venue": None,
        "city": None,
        "address": None,
        "latitude": None,
        "longitude": None,
    }


@pytest.mark.parametrize(
    ("geo", "expected"),
    [
        pytest.param({"latitude": "60.1688", "longitude": "24.9398"}, (60.1688, 24.9398), id="strings"),
        pytest.param({"latitude": 61.7417, "longitude": 26.1142}, (61.7417, 26.1142), id="numbers"),
        pytest.param({"latitude": 0, "longitude": 0}, (0.0, 0.0), id="zero"),
        pytest.param({"latitude": 61.7}, (61.7, None), id="latitude-only"),
        pytest.param({}, (None, None), id="empty"),
        pytest.param("60.1688,24.9398", (None, None), id="string-geo"),
    ],
)
def test_extract_jsonld_coordinates(geo, expected):
    event = minimal_event(location={"name": "Venue", "geo": geo})

    location = extract_single(event)["location"]

    assert (location["latitude"], location["longitude"]) == expected


@pytest.mark.parametrize(
    ("geo", "expected"),
    [
        pytest.param({"latitude": "", "longitude": ""}, (None, None), id="empty-strings"),
        pytest.param({"latitude": "60,1688", "longitude": "24.9398"}, (None, 24.9398), id="decimal-comma"),
        pytest.param({"latitude": "unknown", "longitude": "n/a"}, (None, None), id="text"),
        pytest.param({"latitude": {"value": 60.1}, "longitude": [24.9]}, (None, None), id="wrong-types"),
    ],
)
def test_extract_jsonld_malformed_coordinates_are_missing(geo, expected):
    event = minimal_event("Kept", location={"name": "Venue", "geo": geo})

    result = extract_single(event)

    assert result["name"] == "Kept"
    assert (result["location"]["latitude"], result["location"]["longitude"]) == expected


def test_extract_jsonld_malformed_coordinate_keeps_later_events_in_block():
    html = jsonld_page(
        [
            minimal_event("Before"),
            minimal_event("Bad", location={"geo": {"latitude": "unknown", "longitude": "26.1"}}),
            minimal_event("After", location={"geo": {"latitude": "61.7", "longitude": "26.1"}}),
        ],
        minimal_event("Next block"),
    )

    results = extract_jsonld(html, PAGE_URL)

    assert names(results) == ["Before", "Bad", "After", "Next block"]
    assert results[2]["location"]["latitude"] == 61.7


# --- extract_allevents -------------------------------------------------------


def test_extract_allevents_maps_realistic_record():
    assert extract_single_allevents() == {
        "name": "Stand-up: Ismo Leikola",
        "startDate": "2026-10-03",
        "endDate": "2026-10-03",
        "time": "19:00",
        "price": None,
        "location": {
            "venue": "Joutsa-talo",
            "city": "Joutsa",
            "address": "Jousitie 1",
            "latitude": 61.7417,
            "longitude": 26.1142,
        },
        "description": "Stand-up evening in Jyväskylä & Joutsa.",
        "url": ALLEVENTS_URL,
        "sourceUrls": [ALLEVENTS_URL],
        "sourceType": "allevents",
        "eventId": "3200012345",
    }


def test_extract_allevents_multiple_records_do_not_leak_fields():
    html = allevents_page(
        allevents_record(event_id="1", eventname="First", city="Joutsa"),
        allevents_record(event_id="2", eventname="Second", city=None, street=None, full_address=None),
    )

    results = extract_allevents(html, ALLEVENTS_LISTING_URL)

    assert [(event["eventId"], event["name"]) for event in results] == [("1", "First"), ("2", "Second")]
    assert results[1]["location"]["city"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"eventname": None}, id="missing-name"),
        pytest.param({"eventname": ""}, id="empty-name"),
        pytest.param({"start_time_display": None}, id="missing-date"),
        pytest.param({"start_time_display": "Tomorrow evening"}, id="unparseable-date"),
        pytest.param({"country": "Sweden"}, id="foreign-country"),
    ],
)
def test_extract_allevents_skips_invalid_records(overrides):
    html = allevents_page(
        allevents_record(event_id="1", **overrides),
        allevents_record(event_id="2", eventname="Valid"),
    )

    assert [event["eventId"] for event in extract_allevents(html, None)] == ["2"]


@pytest.mark.parametrize("country", [None, "Finland", "FINLAND", "finland"])
def test_extract_allevents_accepts_finland_or_missing_country(country):
    assert extract_single_allevents(country=country)["eventId"] == "3200012345"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({}, "Jousitie 1", id="street"),
        pytest.param({"street": None}, "Jousitie 1, 19650 Joutsa, Finland", id="full-address"),
        pytest.param({"street": None, "full_address": None}, "Joutsa-talo", id="venue"),
        pytest.param({"street": None, "full_address": None, "location": None}, None, id="none"),
    ],
)
def test_extract_allevents_address_fallback(overrides, expected):
    assert extract_single_allevents(**overrides)["location"]["address"] == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({}, "19:00", id="from-display"),
        pytest.param(
            {"start_time_display": "Sat Oct 3 2026", "short_description": "Ovet klo 18.30"},
            "18:30",
            id="from-description",
        ),
        pytest.param(
            {"start_time_display": "Sat Oct 3 2026", "short_description": "No time"},
            None,
            id="none",
        ),
    ],
)
def test_extract_allevents_time(overrides, expected):
    assert extract_single_allevents(**overrides)["time"] == expected


def test_extract_allevents_description_falls_back_to_description_field():
    result = extract_single_allevents(short_description=None, description="  Full    description ")

    assert result["description"] == "Full description"


@pytest.mark.parametrize(
    ("event_url", "page_url", "expected_url", "expected_sources"),
    [
        pytest.param(ALLEVENTS_URL, ALLEVENTS_LISTING_URL, ALLEVENTS_URL, [ALLEVENTS_URL], id="event-url"),
        pytest.param(None, ALLEVENTS_LISTING_URL, ALLEVENTS_LISTING_URL, [ALLEVENTS_LISTING_URL], id="page-url"),
        pytest.param(None, None, None, [], id="no-url"),
    ],
)
def test_extract_allevents_urls(event_url, page_url, expected_url, expected_sources):
    result = extract_single_allevents(page_url=page_url, event_url=event_url)

    assert result["url"] == expected_url
    assert result["sourceUrls"] == expected_sources


def test_extract_allevents_missing_coordinates_are_none():
    location = extract_single_allevents(latitude=None, longitude=None)["location"]

    assert (location["latitude"], location["longitude"]) == (None, None)


@pytest.mark.parametrize(
    ("latitude", "longitude", "expected"),
    [
        pytest.param("", "", (None, None), id="empty-strings"),
        pytest.param("61,7417", "26.1142", (None, 26.1142), id="decimal-comma"),
        pytest.param("unknown", "", (None, None), id="text"),
    ],
)
def test_extract_allevents_malformed_coordinates_are_missing(latitude, longitude, expected):
    result = extract_single_allevents(latitude=latitude, longitude=longitude)

    assert result["eventId"] == "3200012345"
    assert (result["location"]["latitude"], result["location"]["longitude"]) == expected


def test_extract_allevents_zero_coordinates_are_kept():
    location = extract_single_allevents(latitude="0", longitude="0")["location"]

    assert (location["latitude"], location["longitude"]) == (0.0, 0.0)


def test_extract_allevents_malformed_coordinate_keeps_other_records():
    html = allevents_page(
        allevents_record(event_id="1", eventname="Before"),
        allevents_record(event_id="2", eventname="Bad", latitude="61,7417"),
        allevents_record(event_id="3", eventname="After"),
    )

    results = extract_allevents(html, None)

    assert [event["eventId"] for event in results] == ["1", "2", "3"]
    assert [event["location"]["latitude"] for event in results] == [61.7417, None, 61.7417]


def test_extract_allevents_decodes_json_escapes_and_html_ampersands():
    # allevents_page() serializes with json.dumps, so "ä" and "\n" are
    # embedded as JSON escapes, as on real pages.
    result = extract_single_allevents(
        eventname="Jyväskylä Sinfonia &amp; Friends",
        short_description="Line one\nLine two",
    )

    assert result["name"] == "Jyväskylä Sinfonia & Friends"
    assert result["description"] == "Line one Line two"


def test_extract_allevents_reads_fields_from_record_or_venue():
    record = allevents_record(city=None)
    record["city"] = "Joutsa (top level)"

    results = extract_allevents(allevents_page(record), None)

    assert results[0]["location"]["city"] == "Joutsa (top level)"
    assert results[0]["location"]["address"] == "Jousitie 1"


def test_extract_allevents_ignores_non_text_values():
    record = allevents_record()
    record["location"] = {"name": "Joutsa-talo"}

    result = extract_allevents(allevents_page(record), None)[0]

    assert result["location"]["venue"] is None


def test_extract_allevents_without_records_returns_empty():
    assert extract_allevents(html_page("<p>allevents</p>"), ALLEVENTS_LISTING_URL) == []


def test_extract_allevents_skips_truncated_record_and_keeps_earlier_ones():
    # n8n can truncate large pages mid-record.
    html = allevents_page(
        allevents_record(event_id="1", eventname="Complete"),
        allevents_record(event_id="2", eventname="Truncated"),
    )
    truncated = html[: html.index('"Truncated"') + 5]

    assert [event["eventId"] for event in extract_allevents(truncated, None)] == ["1"]


def test_extract_allevents_does_not_read_fields_outside_records():
    # Real pages contain other "city"/"country" keys after the event array;
    # a record missing a field must not pick them up.
    html = allevents_page(allevents_record(city=None, country=None)) + html_page(
        '<script>var user = {"city": "Stockholm", "country": "Sweden"};</script>'
    )

    results = extract_allevents(html, None)

    assert len(results) == 1
    assert results[0]["location"]["city"] is None


def test_iter_allevents_records_skips_records_nested_in_records():
    outer = allevents_record(event_id="outer")
    outer["related"] = [allevents_record(event_id="inner")]

    records = list(iter_allevents_records(allevents_page(outer)))

    assert [record["event_id"] for record in records] == ["outer"]


# --- extract_allevents: real listing pages -----------------------------------
# Real Allevents pages captured from the n8n "Fetch Event Pages" step.

ALLEVENTS_JYVASKYLA_EVENT_IDS = [
    "200030164959422",
    "200030054049339",
    "200030065813440",
    "200030043857648",
    "200030663377953",
    "3300029317070023",
    "200030458239801",
    "3300030141202431",
    "3300029946165308",
    "200029926001807",
    "200030040726140",
    "200030583736415",
    "3300030135128233",
    "200030663377847",
    "3300030169158008",
]

EXPECTED_EVENT_KEYS = {
    "name",
    "startDate",
    "endDate",
    "time",
    "price",
    "location",
    "description",
    "url",
    "sourceUrls",
    "sourceType",
    "eventId",
}

EXPECTED_LOCATION_KEYS = {"venue", "city", "address", "latitude", "longitude"}


def test_real_allevents_page_extracts_all_finnish_events(allevents_finnish_page):
    results = extract_allevents(allevents_finnish_page, ALLEVENTS_JYVASKYLA_URL)

    assert [event["eventId"] for event in results] == ALLEVENTS_JYVASKYLA_EVENT_IDS
    for event in results:
        assert set(event) == EXPECTED_EVENT_KEYS
        assert set(event["location"]) == EXPECTED_LOCATION_KEYS
        assert event["sourceType"] == "allevents"
        assert event["name"]
        assert event["startDate"] == event["endDate"]
        assert event["location"]["city"] == "Jyväskylä"
        assert isinstance(event["location"]["latitude"], float)
        assert isinstance(event["location"]["longitude"], float)


def test_real_allevents_page_records_do_not_mix_fields(allevents_finnish_page):
    results = extract_allevents(allevents_finnish_page, ALLEVENTS_JYVASKYLA_URL)

    # Each event URL ends with that record's own event id.
    assert all(event["url"].endswith(event["eventId"]) for event in results)
    assert all(event["sourceUrls"] == [event["url"]] for event in results)
    assert len({event["name"] for event in results}) == len(results)


def test_real_allevents_page_first_and_last_records(allevents_finnish_page):
    results = extract_allevents(allevents_finnish_page, ALLEVENTS_JYVASKYLA_URL)

    first_url = (
        "https://allevents.in/jyv%C3%A4skyl%C3%A4/"
        "lost-society-x-hokka-miseria-is-a-state-of-mind-special-guest-st-aurora-lutakko/"
        "200030164959422"
    )
    assert results[0] == {
        "name": "Lost Society x HOKKA - Miseria is a State of Mind + special guest: St. Aurora / Lutakko",
        "startDate": "2026-09-26",
        "endDate": "2026-09-26",
        "time": "19:00",
        "price": None,
        "location": {
            "venue": "Lutakonaukio 3, 40100 Jyväskylä, Finland",
            "city": "Jyväskylä",
            "address": "Lutakonaukio 3, FI-40100 Jyväskylä, Suomi",
            "latitude": 62.239262,
            "longitude": 25.75432,
        },
        "description": (
            "La 26.9.2026 LOST SOCIETY x HOKKA - Miseria Is A State Of Mind @ Lutakko "
            "+ special guest: St. Aurora Ovet klo 19:00, soittoajat: www.jelmu.net "
            "Ei ikärajaa / Rajattu anniskelualue K18 Ennakkoliput 37,40€ jelmu.net "
            "(Jelmun jäsenet 35,40€), alk. 39,90€ lippu"
        ),
        "url": first_url,
        "sourceUrls": [first_url],
        "sourceType": "allevents",
        "eventId": "200030164959422",
    }

    # The last record is followed by the rest of the page, which contains
    # other "city"/"country" keys; its fields must still come from itself.
    last = results[-1]
    assert last["name"] == "Eläkeläiset, Steve ´n´ Seagulls in Laukaa"
    assert (last["startDate"], last["time"]) == ("2026-11-20", "21:00")
    assert last["location"] == {
        "venue": "PEURUNKA AREENA",
        "city": "Jyväskylä",
        "address": "PEURUNKA AREENA, Jyväskylä, LS, Finland",
        "latitude": 62.233002,
        "longitude": 25.733,
    }


def test_real_foreign_allevents_page_records_are_detected_but_skipped(allevents_foreign_page):
    records = list(iter_allevents_records(allevents_foreign_page))

    assert len(records) == 11
    assert {record["venue"]["country"] for record in records} == {"Australia"}
    assert extract_allevents(allevents_foreign_page, None) == []


def test_real_allevents_page_through_extract_event_data(allevents_finnish_page):
    results = extract_event_data(allevents_finnish_page, ALLEVENTS_JYVASKYLA_URL)

    assert [event["eventId"] for event in results] == ALLEVENTS_JYVASKYLA_EVENT_IDS


# --- extract_event_data ------------------------------------------------------


@pytest.mark.parametrize("html", ["", None])
def test_extract_event_data_empty_html(html):
    assert extract_event_data(html, PAGE_URL) == []


def test_extract_event_data_jsonld_only():
    assert extract_event_data(jsonld_page(MUSIC_EVENT), PAGE_URL) == [EXPECTED_MUSIC_EVENT]


def test_extract_event_data_runs_allevents_only_when_page_mentions_allevents():
    records = json.dumps([allevents_record(event_url=None)])
    without_marker = html_page(f"<script>var data = {records};</script>")
    with_marker = html_page(f"<script>var allEvents = {records};</script>")

    assert extract_event_data(without_marker, None) == []
    assert [event["sourceType"] for event in extract_event_data(with_marker, None)] == ["allevents"]


def test_extract_event_data_combines_jsonld_before_allevents():
    html = allevents_page(allevents_record()) + jsonld_page(MUSIC_EVENT)

    results = extract_event_data(html, ALLEVENTS_LISTING_URL)

    assert [event["sourceType"] for event in results] == ["jsonld", "allevents"]


def test_extract_event_data_sample_page(sample_page_html):
    results = extract_event_data(sample_page_html, PAGE_URL)

    assert len(results) == 181
    assert {event["sourceType"] for event in results} == {"jsonld"}
    assert all(event["name"] and event["startDate"] for event in results)
    assert results[0] == {
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


# --- Current behavior: known issues ------------------------------------------
# These tests document the existing implementation, including behavior that is
# probably wrong. They are intentionally explicit so that fixing any of these
# issues becomes a deliberate, visible test change.


def test_allevents_records_inside_json_strings_are_not_detected():
    # Known limitation: records embedded in a JSON-encoded string
    # (e.g. JSON.parse("[{\"event_id\": ...}]")) are not decoded. This format
    # has not been observed on real Allevents pages.
    encoded = json.dumps(json.dumps([allevents_record()]))
    html = html_page(f"<script>window.allevents = JSON.parse({encoded});</script>")

    assert extract_allevents(html, ALLEVENTS_LISTING_URL) == []


@pytest.mark.parametrize(
    ("value", "check"),
    [
        ("nan", math.isnan),
        ("inf", math.isinf),
        ("-inf", math.isinf),
    ],
)
def test_parse_coordinate_accepts_non_finite_values(value, check):
    # Known issue: non-finite values are valid floats and pass through
    # extraction unchanged; later stages must handle them.
    assert check(_parse_coordinate(value))


def test_allevents_numeric_coordinates_are_ignored():
    # Known issue: only string values are read, so numeric coordinates are
    # dropped. Real pages currently use strings.
    location = extract_single_allevents(latitude=61.7417, longitude=26.1142)["location"]

    assert (location["latitude"], location["longitude"]) == (None, None)


def test_get_field_does_not_read_escaped_json():
    # Known limitation: get_field() only reads unescaped quotes. It is no
    # longer used by extract_allevents().
    assert get_field(r'{\"city\":\"Joutsa\"}', "city") is None


def test_get_field_does_not_read_unquoted_values():
    # Known limitation: get_field() only reads quoted string values.
    assert get_field('{"latitude": 61.7417}', "latitude") is None


def test_jsonld_offers_list_gives_no_price():
    # Known issue: schema.org allows (and JamBase uses) a list of offers, but
    # only a single offers object is read.
    event = minimal_event(offers=[{"@type": "Offer", "price": "25.00"}])

    assert extract_single(event)["price"] is None


def test_jsonld_unquoted_type_attribute_is_not_found():
    # Known issue: valid HTML without quotes around the type is ignored.
    html = html_page(jsonld_script(minimal_event(), attributes="type=application/ld+json"))

    assert extract_jsonld(html, PAGE_URL) == []


def test_jsonld_string_address_is_ignored():
    # Known issue: a plain-text address is valid schema.org but is dropped.
    event = minimal_event(location={"name": "Joutsa-talo", "address": "Jousitie 1, Joutsa"})

    location = extract_single(event)["location"]

    assert (location["address"], location["city"]) == (None, None)


def test_is_event_type_matches_any_word_ending_in_event():
    # Known issue: the case-insensitive "Event$" check also matches e.g. "Prevent".
    assert is_event_type("Prevent") is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Known issue: the comment in extract_time() lists "klo 19", but a
        # separator after the hour is required.
        pytest.param("klo 19", None, id="finnish-hour-only-unsupported"),
        pytest.param("klo 19.", None, id="finnish-hour-with-dot-unsupported"),
        pytest.param("7pm", None, id="12-hour-without-minutes-unsupported"),
        # Known issue: no range validation for 12-hour and Finnish times.
        pytest.param("13:00 pm", "25:00", id="invalid-12-hour"),
        pytest.param("klo 25.00", "25:00", id="invalid-finnish"),
        # Known issue: any H:MM pattern is treated as a time.
        pytest.param("John 3:16", "03:16", id="non-time-colon"),
        pytest.param("2026-10-03+03:00", "03:00", id="date-with-utc-offset"),
    ],
)
def test_extract_time_questionable_results(value, expected):
    assert extract_time(value) == expected


@pytest.mark.parametrize(
    ("function", "value", "expected"),
    [
        # Known issue: dates are matched by shape only, not validated.
        pytest.param(normalize_date, "2026-13-45", "2026-13-45", id="normalize-date"),
        pytest.param(parse_allevents_display_date, "Sat Oct 32 2026", "2026-10-32", id="allevents-date"),
    ],
)
def test_impossible_dates_are_accepted(function, value, expected):
    assert function(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Known issue: only &amp; is decoded; other entities and escapes remain.
        (r"&lt;b&gt;", r"&lt;b&gt;"),
        ("Rock &#39;n&#39; Roll", "Rock &#39;n&#39; Roll"),
        (r"Line\nbreak", r"Line\nbreak"),
    ],
)
def test_decode_leaves_other_entities_and_escapes(value, expected):
    assert decode(value) == expected


def test_sample_page_prices_are_all_missing(sample_page_html):
    # Known issue: consequence of the offers-list issue on real JamBase data.
    results = extract_event_data(sample_page_html, PAGE_URL)

    assert all(event["price"] is None for event in results)
