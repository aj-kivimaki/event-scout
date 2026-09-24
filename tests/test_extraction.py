import copy
import json
from pathlib import Path

import pytest

from src.event_digest.extraction import (
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

ALLEVENTS_FIELDS = {
    "event_id": "3200012345",
    "eventname": "Stand-up: Ismo Leikola",
    "start_time_display": "Sat Oct 3 2026 at 07:00 pm",
    "location": "Joutsa-talo",
    "city": "Joutsa",
    "street": "Jousitie 1",
    "full_address": "Jousitie 1, 19650 Joutsa, Finland",
    "latitude": "61.7417",
    "longitude": "26.1142",
    "country": "Finland",
    "event_url": ALLEVENTS_URL,
    "short_description": "Stand-up evening in Jyväskylä & Joutsa.",
}


def allevents_record(**overrides) -> str:
    """Build one Allevents record that the current extractor can read.

    Known issue: extract_allevents() locates records with a pattern that
    requires backslash-escaped quotes (`\\"event_id\\"`), but get_field()
    only reads unescaped quotes (`"event_id"`). Neither plain JSON nor escaped
    JSON works on its own (see the known-issue tests), so this builder emits an
    escaped marker followed by the plain JSON fields. When the extractor is
    fixed, this is the one place the fixture format should change.
    """

    fields = {**ALLEVENTS_FIELDS, **overrides}
    fields = {key: value for key, value in fields.items() if value is not None}
    marker = (
        rf'\"event_id\":\"{fields.get("event_id", "0")}\",'
        rf'\"eventname\":\"marker\"'
    )
    return f"{marker} {json.dumps(fields)}"


def allevents_page(*records: str) -> str:
    return html_page(
        "<script>window.allevents_data = [",
        ",\n".join(records),
        "];</script>",
    )


def extract_single_allevents(page_url: str | None = ALLEVENTS_LISTING_URL, **overrides) -> dict:
    results = extract_allevents(allevents_page(allevents_record(**overrides)), page_url)
    assert len(results) == 1
    return results[0]


@pytest.fixture(scope="module")
def sample_page_html() -> str:
    return SAMPLE_PAGE_PATH.read_text(encoding="utf-8")


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


def test_extract_allevents_decodes_escaped_text():
    result = extract_single_allevents(eventname="Jyväskylä Sinfonia", location="Paviljonki")

    assert result["name"] == "Jyväskylä Sinfonia"


def test_extract_allevents_without_records_returns_empty():
    assert extract_allevents(html_page("<p>allevents</p>"), ALLEVENTS_LISTING_URL) == []


# --- extract_event_data ------------------------------------------------------


@pytest.mark.parametrize("html", ["", None])
def test_extract_event_data_empty_html(html):
    assert extract_event_data(html, PAGE_URL) == []


def test_extract_event_data_jsonld_only():
    assert extract_event_data(jsonld_page(MUSIC_EVENT), PAGE_URL) == [EXPECTED_MUSIC_EVENT]


def test_extract_event_data_runs_allevents_only_when_page_mentions_allevents():
    record = allevents_record(event_url=None)
    without_marker = html_page(f"<script>var data = [{record}];</script>")
    with_marker = html_page(f"<script>var allEvents = [{record}];</script>")

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


PLAIN_ALLEVENTS_JSON = json.dumps(
    [{key: ALLEVENTS_FIELDS[key] for key in ("event_id", "eventname", "start_time_display", "city")}]
)


@pytest.mark.parametrize(
    "script_body",
    [
        pytest.param(f"window.allevents = {PLAIN_ALLEVENTS_JSON};", id="plain-json"),
        pytest.param(f"window.allevents = JSON.parse({json.dumps(PLAIN_ALLEVENTS_JSON)});", id="escaped-json"),
    ],
)
def test_allevents_extraction_finds_nothing_in_plain_or_escaped_json(script_body):
    # Known issue: the record-locating regex requires escaped quotes while
    # get_field() requires unescaped quotes, so neither real-world format
    # produces events.
    assert extract_allevents(html_page(f"<script>{script_body}</script>"), ALLEVENTS_LISTING_URL) == []


def test_get_field_does_not_read_escaped_json():
    # Known issue: see above.
    assert get_field(r'{\"city\":\"Joutsa\"}', "city") is None


def test_get_field_does_not_read_unquoted_values():
    # Known issue: numeric Allevents values (e.g. coordinates) are ignored.
    assert get_field('{"latitude": 61.7417}', "latitude") is None


@pytest.mark.parametrize("latitude", ["", "61,7417", "unknown"])
def test_allevents_invalid_coordinate_raises(latitude):
    # Known issue: float() is not guarded, so one bad record fails the page.
    with pytest.raises(ValueError):
        extract_allevents(allevents_page(allevents_record(latitude=latitude)), None)


def test_jsonld_offers_list_gives_no_price():
    # Known issue: schema.org allows (and JamBase uses) a list of offers, but
    # only a single offers object is read.
    event = minimal_event(offers=[{"@type": "Offer", "price": "25.00"}])

    assert extract_single(event)["price"] is None


def test_jsonld_invalid_coordinate_drops_rest_of_block():
    # Known issue: the ValueError from float() is caught per script block, so
    # the bad event and all later events in the same block are lost.
    html = jsonld_page(
        [
            minimal_event("Before"),
            minimal_event("Bad", location={"geo": {"latitude": "unknown", "longitude": "26.1"}}),
            minimal_event("After"),
        ],
        minimal_event("Next block"),
    )

    assert names(extract_jsonld(html, PAGE_URL)) == ["Before", "Next block"]


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


def test_allevents_description_keeps_escaped_newlines():
    # Known issue: consequence of decode() not handling "\n" escapes.
    result = extract_single_allevents(short_description="Line one\nLine two")

    assert result["description"] == r"Line one\nLine two"


def test_sample_page_prices_are_all_missing(sample_page_html):
    # Known issue: consequence of the offers-list issue on real JamBase data.
    results = extract_event_data(sample_page_html, PAGE_URL)

    assert all(event["price"] is None for event in results)
