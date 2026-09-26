import math
import re
import unicodedata


def deduplicate_events(events: list[dict]) -> list[dict]:
    """Merge duplicate events while preserving useful source data."""

    groups: list[dict] = []

    for event in events:
        artist = get_artist_name(event.get("name"))
        event_date = get_event_date(event)
        coordinates = get_coordinates(event)

        if not artist or not event_date:
            groups.append({
                **event,
                "sourceUrls": (
                    [event["url"]]
                    if event.get("url")
                    else []
                ),
            })
            continue

        matching_group = None

        for existing in groups:
            existing_artist = get_artist_name(
                existing.get("name")
            )
            existing_date = get_event_date(existing)

            if (
                artist != existing_artist
                or event_date != existing_date
            ):
                continue

            existing_coordinates = get_coordinates(
                existing
            )

            if coordinates and existing_coordinates:
                distance = distance_between(
                    coordinates,
                    existing_coordinates,
                )

                if distance > 5:
                    continue

            matching_group = existing
            break

        if matching_group:
            merge_event(
                matching_group,
                event,
            )
        else:
            groups.append({
                **event,
                "sourceUrls": list(
                    dict.fromkeys([
                        *(event.get("sourceUrls") or []),
                        *(
                            [event["url"]]
                            if event.get("url")
                            else []
                        ),
                    ])
                ),
            })

    return groups


def normalize(value) -> str:
    """Normalize text for comparison."""

    value = str(value or "").lower()

    value = unicodedata.normalize(
        "NFD",
        value,
    )

    value = "".join(
        character
        for character in value
        if unicodedata.category(character) != "Mn"
    )

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    return value.strip()


def get_artist_name(name) -> str:
    """Extract a normalized artist name from an event name."""

    value = str(name or "")

    value = value.split("@")[0]

    value = re.sub(
        r"\s+-\s+[^-]+?\s+-\s+[^-]+?\s+-\s+\w+\s+\d{1,2},\s+\d{4}$",
        "",
        value,
        flags=re.IGNORECASE,
    )

    return normalize(value)


def get_event_date(event: dict) -> str:
    """Get the event date in YYYY-MM-DD format."""

    start_date = event.get("startDate")

    if not start_date:
        return ""

    return start_date[:10]


def get_coordinates(event: dict) -> dict | None:
    """Return valid event coordinates."""

    location = event.get("location") or {}

    try:
        latitude = float(location.get("latitude"))
        longitude = float(location.get("longitude"))
    except (TypeError, ValueError):
        return None

    if not (
        math.isfinite(latitude)
        and math.isfinite(longitude)
    ):
        return None

    return {
        "lat": latitude,
        "lon": longitude,
    }


def distance_between(
    first: dict | None,
    second: dict | None,
) -> float:
    """Calculate distance between two coordinates in km."""

    if not first or not second:
        return math.inf

    earth_radius_km = 6371

    d_lat = math.radians(
        second["lat"] - first["lat"]
    )
    d_lon = math.radians(
        second["lon"] - first["lon"]
    )

    x = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(first["lat"]))
        * math.cos(math.radians(second["lat"]))
        * math.sin(d_lon / 2) ** 2
    )

    return (
        earth_radius_km
        * 2
        * math.atan2(
            math.sqrt(x),
            math.sqrt(1 - x),
        )
    )


def merge_event(
    existing: dict,
    event: dict,
) -> None:
    """Merge useful information from an event into an existing group."""

    urls = [
        *(existing.get("sourceUrls") or []),
        *(event.get("sourceUrls") or []),
        *(
            [event["url"]]
            if event.get("url")
            else []
        ),
    ]

    existing["sourceUrls"] = list(
        dict.fromkeys(
            url
            for url in urls
            if url
        )
    )

    if (
        event.get("name")
        and (
            not existing.get("name")
            or len(event["name"])
            > len(existing["name"])
        )
    ):
        existing["name"] = event["name"]

    if (
        not existing.get("description")
        and event.get("description")
    ):
        existing["description"] = event["description"]

    if (
        not get_coordinates(existing)
        and get_coordinates(event)
    ):
        existing["location"] = {
            **(existing.get("location") or {}),
            **(event.get("location") or {}),
        }

        existing["distanceKm"] = event.get(
            "distanceKm"
        )

    # "location" may be missing or explicitly None.
    event_location = event.get("location") or {}

    existing["location"] = {
        **event_location,
        **(existing.get("location") or {}),
    }

    if (
        not existing["location"].get("venue")
        and event_location.get("venue")
    ):
        existing["location"]["venue"] = (
            event_location["venue"]
        )

    if (
        not existing["location"].get("city")
        and event_location.get("city")
    ):
        existing["location"]["city"] = (
            event_location["city"]
        )

    if (
        not existing["location"].get("address")
        and event_location.get("address")
    ):
        existing["location"]["address"] = (
            event_location["address"]
        )

    if (
        existing.get("distanceKm") is None
        and event.get("distanceKm") is not None
    ):
        existing["distanceKm"] = event["distanceKm"]