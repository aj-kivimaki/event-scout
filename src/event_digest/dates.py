import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


HELSINKI = ZoneInfo("Europe/Helsinki")

MONTH_NAMES = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def calculate_date_range(
    lookahead_weeks: int,
    today: date | None = None,
) -> tuple[date, date]:
    """Calculate the next complete Monday-Sunday date range.

    Uses the current Helsinki date unless `today` is provided.
    """

    if today is None:
        today = datetime.now(HELSINKI).date()

    days_until_monday = (7 - today.weekday()) % 7

    # If today is Monday, use the following Monday.
    if days_until_monday == 0:
        days_until_monday = 7

    start_date = today + timedelta(
        days=days_until_monday
    )

    end_date = start_date + timedelta(
        days=(lookahead_weeks * 7) - 1
    )

    return start_date, end_date


def max_lookahead_weeks(
    today: date | None = None,
) -> int:
    """Return the largest lookahead whose date range fits in a date.

    The bound is technical, not a business rule: the end date calculated by
    calculate_date_range() must not exceed date.max. It depends on the start
    date, so it is calculated rather than fixed.
    """

    start_date, _ = calculate_date_range(
        1,
        today=today,
    )

    return ((date.max - start_date).days + 1) // 7


def filter_events_by_date(
    events: list[dict],
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Keep events that occur within the configured date range."""

    results = []

    for event in events:
        event_start = event.get("startDate")

        if not event_start:
            continue

        start = event_start[:10]
        event_end = (
            event.get("endDate") or event_start
        )[:10]

        if start_date <= start <= end_date:
            results.append(event)
            continue

        if start < start_date or event_end > end_date:
            occurrence_dates = extract_occurrence_dates(
                event.get("description"),
                start_date,
                end_date,
            )

            for occurrence_date in occurrence_dates:
                results.append({
                    **event,
                    "startDate": (
                        f"{occurrence_date}T13:00:00"
                    ),
                    "endDate": occurrence_date,
                    "occurrenceDate": occurrence_date,
                })

    return results


def extract_occurrence_dates(
    description: str | None,
    start_date: str,
    end_date: str,
) -> list[str]:
    """Extract occurrence dates from an event description."""

    if not description:
        return []

    dates = set()

    iso_matches = re.findall(
        r"\b20\d{2}-\d{2}-\d{2}\b",
        description,
    )

    for value in iso_matches:
        if start_date <= value <= end_date:
            dates.add(value)

    month_pattern = re.compile(
        rf"\b({'|'.join(MONTH_NAMES)})"
        rf"\s+(\d{{1,2}}),\s+(20\d{{2}})\b",
        re.IGNORECASE,
    )

    for match in month_pattern.finditer(description):
        month = next(
            index
            for index, name in enumerate(
                MONTH_NAMES,
                start=1,
            )
            if name.lower()
            == match.group(1).lower()
        )

        day = int(match.group(2))
        year = int(match.group(3))

        value = f"{year}-{month:02d}-{day:02d}"

        if start_date <= value <= end_date:
            dates.add(value)

    return sorted(dates)