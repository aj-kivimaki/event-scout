import json
import math
import re


def decode(value: object | None) -> str | None:
    """Decode escaped text values."""

    if value is None:
        return None

    text = str(value)

    text = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda match: chr(int(match.group(1), 16)),
        text,
    )

    return (
        text
        .replace(r"\/", "/")
        .replace(r"\"", '"')
        .replace("&amp;", "&")
    )


def clean_text(value: object | None) -> str | None:
    """Normalize whitespace in text values."""

    if value is None:
        return None

    return " ".join(str(value).split()).strip()


def _parse_coordinate(value: object | None) -> float | None:
    """Convert a coordinate to a finite float.

    Missing, malformed and non-finite (NaN/inf) values are treated as
    missing coordinates.
    """

    if value is None:
        return None

    try:
        coordinate = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(coordinate):
        return None

    return coordinate


def normalize_date(value: object | None) -> str | None:
    """Normalize an ISO date value to YYYY-MM-DD."""

    if not value:
        return None

    match = re.match(
        r"^(\d{4})-(\d{2})-(\d{2})",
        str(value),
    )

    if not match:
        return None

    return (
        f"{match.group(1)}-"
        f"{match.group(2)}-"
        f"{match.group(3)}"
    )


def extract_time(value: object | None) -> str | None:
    """Extract a time from common event-page formats."""

    if not value:
        return None

    text = str(value)

    # 12-hour format: 07:00 pm / 09:00 PM
    match = re.search(
        r"\b(\d{1,2}):(\d{2})\s*(am|pm)\b",
        text,
        re.IGNORECASE,
    )

    if match:
        hour = int(match.group(1))
        minute = match.group(2)
        period = match.group(3).lower()

        if period == "pm" and hour != 12:
            hour += 12

        if period == "am" and hour == 12:
            hour = 0

        return f"{hour:02d}:{minute}"

    # 24-hour format
    match = re.search(
        r"(?:^|[^\d])([01]?\d|2[0-3]):([0-5]\d)(?!\d)",
        text,
    )

    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"

    # Finnish format: klo 19 / klo 19.30 / kl. 19.30
    match = re.search(
        r"\b(?:klo|kl\.?)\s*(\d{1,2})(?:[:.](\d{2}))?\b",
        text,
        re.IGNORECASE,
    )

    if match:
        hour = int(match.group(1))
        minute = match.group(2) or "00"

        return f"{hour:02d}:{minute}"

    return None


def parse_allevents_display_date(
    display: object | None,
) -> str | None:
    """Parse an Allevents display date into YYYY-MM-DD."""

    if not display:
        return None

    match = re.match(
        r"^[A-Za-z]{3}\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})",
        str(display),
        re.IGNORECASE,
    )

    if not match:
        return None

    months = {
        "jan": "01",
        "feb": "02",
        "mar": "03",
        "apr": "04",
        "may": "05",
        "jun": "06",
        "jul": "07",
        "aug": "08",
        "sep": "09",
        "oct": "10",
        "nov": "11",
        "dec": "12",
    }

    month = months.get(match.group(1).lower())

    if not month:
        return None

    return (
        f"{match.group(3)}-"
        f"{month}-"
        f"{int(match.group(2)):02d}"
    )


def is_event_type(event_type: object) -> bool:
    """Return whether a JSON-LD type represents an event."""

    if isinstance(event_type, str):
        return (
            event_type == "Event"
            or bool(
                re.search(
                    r"Event$",
                    event_type,
                    re.IGNORECASE,
                )
            )
        )

    if isinstance(event_type, list):
        return any(
            isinstance(item, str)
            and (
                item == "Event"
                or bool(
                    re.search(
                        r"Event$",
                        item,
                        re.IGNORECASE,
                    )
                )
            )
            for item in event_type
        )

    return False


def get_jsonld_time(event: dict) -> str | None:
    """Extract the most useful event time from JSON-LD."""

    start_date = (
        event.get("startDate")
        or event.get("startTime")
    )

    time_from_start = extract_time(start_date)

    if time_from_start and time_from_start != "00:00":
        return time_from_start

    time_from_description = extract_time(
        event.get("description")
    )

    if time_from_description:
        return time_from_description

    return time_from_start


def collect_jsonld_events(
    value: object,
    result: list[dict],
) -> list[dict]:
    """Recursively collect Event objects from JSON-LD."""

    if not value:
        return result

    if isinstance(value, list):
        for item in value:
            collect_jsonld_events(
                item,
                result,
            )

        return result

    if not isinstance(value, dict):
        return result

    if is_event_type(value.get("@type")):
        result.append(value)

    if isinstance(value.get("@graph"), list):
        collect_jsonld_events(
            value["@graph"],
            result,
        )

    if value.get("event"):
        collect_jsonld_events(
            value["event"],
            result,
        )

    return result


def city_from_plain_address(address: str | None) -> str | None:
    """Return the city from a plain-text "City, Country" address.

    Only this simple two-part shape is recognized; other address strings
    (for example "Street 1, City") return None.
    """

    if not address:
        return None

    parts = [
        part.strip()
        for part in address.split(",")
    ]

    if len(parts) != 2 or not all(parts):
        return None

    if any(character.isdigit() for character in parts[0]):
        return None

    return parts[0]


def extract_jsonld(
    html: str,
    page_url: str | None,
) -> list[dict]:
    """Extract event data from JSON-LD Event objects."""

    results = []

    matches = re.finditer(
        r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>'
        r'([\s\S]*?)'
        r"</script>",
        html,
        re.IGNORECASE,
    )

    for match in matches:
        raw_json = match.group(1).strip()

        if not raw_json:
            continue

        try:
            parsed = json.loads(raw_json)

            events = collect_jsonld_events(
                parsed,
                [],
            )

            for event in events:
                name = clean_text(
                    event.get("name")
                )

                if not name:
                    continue

                start_date = normalize_date(
                    event.get("startDate")
                )

                if not start_date:
                    continue

                location = (
                    event.get("location")
                    if isinstance(
                        event.get("location"),
                        dict,
                    )
                    else {}
                )

                address = (
                    location.get("address")
                    if isinstance(
                        location.get("address"),
                        dict,
                    )
                    else {}
                )

                # schema.org also allows a plain-text address.
                address_text = (
                    location.get("address")
                    if isinstance(
                        location.get("address"),
                        str,
                    )
                    else None
                )

                city = clean_text(
                    address.get("addressLocality")
                    or location.get("addressLocality")
                    or city_from_plain_address(address_text)
                )

                venue = clean_text(
                    location.get("name")
                )

                geo = location.get("geo")
                geo = (
                    geo
                    if isinstance(geo, dict)
                    else {}
                )

                latitude = geo.get("latitude")
                longitude = geo.get("longitude")

                url = event.get("url") or page_url

                results.append({
                    "name": name,
                    "startDate": start_date,
                    "endDate": (
                        normalize_date(
                            event.get("endDate")
                        )
                        or start_date
                    ),
                    "time": get_jsonld_time(event),
                    "price": (
                        event.get("offers", {}).get("price")
                        if isinstance(
                            event.get("offers"),
                            dict,
                        )
                        else None
                    ),
                    "location": {
                        "venue": venue,
                        "city": city,
                        "address": clean_text(
                            address.get("streetAddress")
                            or address_text
                        ),
                        "latitude": _parse_coordinate(
                            latitude
                        ),
                        "longitude": _parse_coordinate(
                            longitude
                        ),
                    },
                    "description": clean_text(
                        event.get("description")
                    ),
                    "url": url,
                    "sourceUrls": (
                        [url]
                        if url
                        else []
                    ),
                    "sourceType": "jsonld",
                })

        except (
            ValueError,
            TypeError,
            json.JSONDecodeError,
        ):
            # Ignore invalid JSON-LD.
            continue

    return results


ALLEVENTS_RECORD_START = re.compile(
    r'\{\s*"event_id"\s*:'
)


def iter_allevents_records(html: str):
    """Yield Allevents event records embedded as JSON objects in the page.

    Allevents listing pages embed events in script assignments such as
    `_this.events_data = [{"event_id": "...", "eventname": "...", ...}]`.
    Each record is decoded as a complete JSON object so that fields cannot
    leak between records or from the rest of the page.
    """

    decoder = json.JSONDecoder()
    record_end = -1

    for match in ALLEVENTS_RECORD_START.finditer(html):
        # Skip matches nested inside an already decoded record.
        if match.start() < record_end:
            continue

        try:
            record, record_end = decoder.raw_decode(
                html,
                match.start(),
            )
        except json.JSONDecodeError:
            # Ignore truncated or otherwise invalid records.
            continue

        if isinstance(record, dict):
            yield record


def get_allevents_field(
    record: dict,
    field: str,
) -> str | None:
    """Return a text field from an Allevents record or its venue."""

    value = record.get(field)

    if value is None and isinstance(record.get("venue"), dict):
        value = record["venue"].get(field)

    if not isinstance(value, str):
        return None

    return decode(value)


def extract_allevents(
    html: str,
    page_url: str | None,
) -> list[dict]:
    """Extract event data from Allevents listing pages."""

    results = []

    for record in iter_allevents_records(html):
        event_id = get_allevents_field(
            record,
            "event_id",
        )
        name = get_allevents_field(
            record,
            "eventname",
        )

        if not event_id or not name:
            continue

        country = get_allevents_field(
            record,
            "country",
        )

        # Ignore foreign events on Allevents listing pages.
        if country and country.lower() != "finland":
            continue

        start_display = get_allevents_field(
            record,
            "start_time_display",
        )

        event_date = parse_allevents_display_date(
            start_display
        )

        if not event_date:
            continue

        venue = get_allevents_field(
            record,
            "location",
        )
        city = get_allevents_field(
            record,
            "city",
        )
        street = get_allevents_field(
            record,
            "street",
        )
        full_address = get_allevents_field(
            record,
            "full_address",
        )
        latitude = get_allevents_field(
            record,
            "latitude",
        )
        longitude = get_allevents_field(
            record,
            "longitude",
        )
        event_url = get_allevents_field(
            record,
            "event_url",
        )

        description = (
            get_allevents_field(
                record,
                "short_description",
            )
            or get_allevents_field(
                record,
                "description",
            )
        )

        time = extract_time(
            start_display
        )

        if not time:
            time = extract_time(
                description
            )

        results.append({
            "name": clean_text(name),
            "startDate": event_date,
            "endDate": event_date,
            "time": time,
            "price": None,
            "location": {
                "venue": clean_text(venue),
                "city": clean_text(city),
                "address": clean_text(
                    street
                    or full_address
                    or venue
                ),
                "latitude": _parse_coordinate(
                    latitude
                ),
                "longitude": _parse_coordinate(
                    longitude
                ),
            },
            "description": clean_text(
                description
            ),
            "url": event_url or page_url,
            "sourceUrls": (
                [event_url]
                if event_url
                else [page_url]
                if page_url
                else []
            ),
            "sourceType": "allevents",
            "eventId": event_id,
        })

    return results


def extract_event_data(
    html: str,
    page_url: str | None,
) -> list[dict]:
    """Extract events from supported page formats."""

    if not html:
        return []

    jsonld_events = extract_jsonld(
        html,
        page_url,
    )

    allevents_events = []

    if "allevents" in html.lower():
        allevents_events = extract_allevents(
            html,
            page_url,
        )

    return [
        *jsonld_events,
        *allevents_events,
    ]