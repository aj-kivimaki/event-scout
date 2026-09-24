from datetime import date, datetime

import pytest

from src.event_digest.dates import (
    HELSINKI,
    calculate_date_range,
    extract_occurrence_dates,
    filter_events_by_date,
)

# Three-week range starting Monday 2026-09-28 and ending Sunday 2026-10-18.
RANGE_START = "2026-09-28"
RANGE_END = "2026-10-18"


def make_event(**fields) -> dict:
    return {"name": "Test Event", **fields}


# --- calculate_date_range ----------------------------------------------------


@pytest.mark.parametrize(
    "today",
    [
        pytest.param(date(2026, 9, 22), id="tuesday"),
        pytest.param(date(2026, 9, 25), id="friday"),
        pytest.param(date(2026, 9, 27), id="sunday"),
    ],
)
def test_calculate_date_range_starts_next_monday(today):
    start_date, _ = calculate_date_range(3, today=today)

    assert start_date == date(2026, 9, 28)
    assert start_date.weekday() == 0


def test_calculate_date_range_on_monday_uses_following_monday():
    start_date, end_date = calculate_date_range(1, today=date(2026, 9, 21))

    assert start_date == date(2026, 9, 28)
    assert end_date == date(2026, 10, 4)


@pytest.mark.parametrize(
    ("lookahead_weeks", "expected_end"),
    [
        (1, date(2026, 10, 4)),
        (2, date(2026, 10, 11)),
        (3, date(2026, 10, 18)),
        (4, date(2026, 10, 25)),
    ],
)
def test_calculate_date_range_end_date_matches_lookahead_weeks(
    lookahead_weeks,
    expected_end,
):
    start_date, end_date = calculate_date_range(
        lookahead_weeks,
        today=date(2026, 9, 25),
    )

    assert end_date == expected_end
    assert end_date.weekday() == 6
    assert (end_date - start_date).days == lookahead_weeks * 7 - 1


def test_calculate_date_range_crosses_year_boundary():
    start_date, end_date = calculate_date_range(2, today=date(2026, 12, 30))

    assert start_date == date(2027, 1, 4)
    assert end_date == date(2027, 1, 17)


def test_calculate_date_range_defaults_to_current_helsinki_date():
    helsinki_today = datetime.now(HELSINKI).date()

    assert calculate_date_range(3) == calculate_date_range(
        3,
        today=helsinki_today,
    )


# --- filter_events_by_date: events inside the range ---------------------------


@pytest.mark.parametrize(
    "start",
    [
        pytest.param(RANGE_START, id="first-day"),
        pytest.param("2026-10-07T19:00:00", id="middle-with-time"),
        pytest.param("2026-10-18T23:30:00+03:00", id="last-day-with-offset"),
    ],
)
def test_filter_keeps_events_starting_inside_range(start):
    event = make_event(startDate=start)

    assert filter_events_by_date([event], RANGE_START, RANGE_END) == [event]


def test_filter_keeps_in_range_event_unchanged_even_with_other_dates_in_description():
    event = make_event(
        startDate="2026-10-01T18:00:00",
        description="Also on 2026-10-08 and October 15, 2026.",
    )

    results = filter_events_by_date([event], RANGE_START, RANGE_END)

    assert results == [event]
    assert "occurrenceDate" not in results[0]


def test_filter_preserves_input_order():
    events = [
        make_event(name="Late", startDate="2026-10-15"),
        make_event(name="Early", startDate="2026-09-30"),
    ]

    results = filter_events_by_date(events, RANGE_START, RANGE_END)

    assert [event["name"] for event in results] == ["Late", "Early"]


# --- filter_events_by_date: missing or out-of-range events --------------------


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(make_event(), id="missing-startDate"),
        pytest.param(make_event(startDate=None), id="none-startDate"),
        pytest.param(make_event(startDate=""), id="empty-startDate"),
    ],
)
def test_filter_skips_events_without_start_date(event):
    assert filter_events_by_date([event], RANGE_START, RANGE_END) == []


@pytest.mark.parametrize(
    "event",
    [
        pytest.param(
            make_event(startDate="2026-09-27T20:00:00"),
            id="day-before-range",
        ),
        pytest.param(
            make_event(startDate="2026-10-19T10:00:00"),
            id="day-after-range",
        ),
        pytest.param(
            make_event(
                startDate="2026-09-01",
                endDate="2026-12-31",
                description="Open daily. See you on 2026-11-05!",
            ),
            id="long-running-no-matching-occurrence",
        ),
        pytest.param(
            make_event(
                startDate="2026-11-01",
                description="Previous show was on September 30, 2025.",
            ),
            id="after-range-description-date-other-year",
        ),
    ],
)
def test_filter_drops_out_of_range_events_without_matching_occurrences(event):
    assert filter_events_by_date([event], RANGE_START, RANGE_END) == []


# --- filter_events_by_date: occurrence dates from descriptions ----------------


def test_filter_expands_long_running_event_into_occurrences():
    event = make_event(
        startDate="2026-09-01T10:00:00",
        endDate="2026-12-31",
        description="Performances on 2026-10-03 and October 10, 2026.",
        url="https://example.com/show",
    )

    results = filter_events_by_date([event], RANGE_START, RANGE_END)

    assert results == [
        {
            **event,
            "startDate": "2026-10-03T13:00:00",
            "endDate": "2026-10-03",
            "occurrenceDate": "2026-10-03",
        },
        {
            **event,
            "startDate": "2026-10-10T13:00:00",
            "endDate": "2026-10-10",
            "occurrenceDate": "2026-10-10",
        },
    ]


def test_filter_expands_event_starting_after_range_with_occurrence_inside():
    event = make_event(
        startDate="2026-11-01",
        description="Preview night: 2026-10-16.",
    )

    results = filter_events_by_date([event], RANGE_START, RANGE_END)

    assert [result["occurrenceDate"] for result in results] == ["2026-10-16"]


def test_filter_does_not_mutate_original_event():
    event = make_event(
        startDate="2026-09-01",
        endDate="2026-12-31",
        description="Show on 2026-10-03.",
    )
    original = dict(event)

    filter_events_by_date([event], RANGE_START, RANGE_END)

    assert event == original


# --- extract_occurrence_dates -------------------------------------------------


@pytest.mark.parametrize("description", [None, ""])
def test_extract_occurrence_dates_handles_empty_description(description):
    assert extract_occurrence_dates(description, RANGE_START, RANGE_END) == []


def test_extract_occurrence_dates_finds_iso_dates_within_range():
    description = (
        "Dates: 2026-09-27, 2026-09-28, 2026-10-05, 2026-10-18, 2026-10-19."
    )

    assert extract_occurrence_dates(description, RANGE_START, RANGE_END) == [
        "2026-09-28",
        "2026-10-05",
        "2026-10-18",
    ]


def test_extract_occurrence_dates_finds_month_day_year_dates():
    description = (
        "Join us on October 2, 2026 or october 9, 2026. "
        "Final show OCTOBER 30, 2026."
    )

    assert extract_occurrence_dates(description, RANGE_START, RANGE_END) == [
        "2026-10-02",
        "2026-10-09",
    ]


def test_extract_occurrence_dates_deduplicates_and_sorts_mixed_formats():
    description = (
        "October 12, 2026 at the hall. Repeat on 2026-10-01. "
        "(2026-10-12 is sold out.)"
    )

    assert extract_occurrence_dates(description, RANGE_START, RANGE_END) == [
        "2026-10-01",
        "2026-10-12",
    ]


@pytest.mark.parametrize(
    "description",
    [
        pytest.param("Doors open 19:00, tickets 20 EUR.", id="no-dates"),
        pytest.param("2.10.2026 klo 19", id="finnish-format-not-supported"),
        pytest.param("Oct 2, 2026", id="abbreviated-month-not-supported"),
        pytest.param("October 2 2026", id="missing-comma-not-supported"),
    ],
)
def test_extract_occurrence_dates_ignores_unsupported_formats(description):
    assert extract_occurrence_dates(description, RANGE_START, RANGE_END) == []
