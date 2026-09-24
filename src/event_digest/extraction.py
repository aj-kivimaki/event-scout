import json
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


def get_field(raw: str, field: str) -> str | None:
    """Extract a quoted field from raw event data."""

    pattern = (
        rf'"{re.escape(field)}"\s*:\s*"((?:\\.|[^"])*)"'
    )

    match = re.search(pattern, raw)

    if not match:
        return None

    return decode(match.group(1))


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
        r"\b(?:klo|kl\.?)\s*(\d{1,2})(?::|\.)(\d{2})?\b",
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

                city = clean_text(
                    address.get("addressLocality")
                    or location.get("addressLocality")
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
                        ),
                        "latitude": (
                            float(latitude)
                            if latitude is not None
                            else None
                        ),
                        "longitude": (
                            float(longitude)
                            if longitude is not None
                            else None
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


def extract_allevents(
    html: str,
    page_url: str | None,
) -> list[dict]:
    """Extract event data from Allevents listing pages."""

    results = []

    matches = list(
        re.finditer(
            r'\\"?event_id\\"?\s*:\s*\\"?[^"]+\\"?\s*,'
            r'\s*\\"?eventname\\"?',
            html,
        )
    )

    for index, match in enumerate(matches):
        start = match.start()

        if index + 1 < len(matches):
            end = matches[index + 1].start()
        else:
            end = len(html)

        raw = html[start:end]

        event_id = get_field(
            raw,
            "event_id",
        )
        name = get_field(
            raw,
            "eventname",
        )

        if not event_id or not name:
            continue

        country = get_field(
            raw,
            "country",
        )

        # Ignore foreign events on Allevents listing pages.
        if country and country.lower() != "finland":
            continue

        start_display = get_field(
            raw,
            "start_time_display",
        )

        event_date = parse_allevents_display_date(
            start_display
        )

        if not event_date:
            continue

        venue = get_field(
            raw,
            "location",
        )
        city = get_field(
            raw,
            "city",
        )
        street = get_field(
            raw,
            "street",
        )
        full_address = get_field(
            raw,
            "full_address",
        )
        latitude = get_field(
            raw,
            "latitude",
        )
        longitude = get_field(
            raw,
            "longitude",
        )
        event_url = get_field(
            raw,
            "event_url",
        )

        description = (
            get_field(
                raw,
                "short_description",
            )
            or get_field(
                raw,
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
                "latitude": (
                    float(latitude)
                    if latitude is not None
                    else None
                ),
                "longitude": (
                    float(longitude)
                    if longitude is not None
                    else None
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