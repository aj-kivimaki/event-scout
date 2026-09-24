from math import asin, cos, isfinite, radians, sin, sqrt


CITY_COORDINATES = {
    "Joutsa": (61.7417, 26.1142),
    "Jyväskylä": (62.2426, 25.7473),
    "Lahti": (60.9827, 25.6615),
    "Heinola": (61.2056, 26.0388),
    "Jämsä": (61.8642, 25.1900),
    "Hartola": (61.5869, 26.0156),
    "Sysmä": (61.5015, 25.6832),
    "Mäntyharju": (61.4167, 26.8833),
    "Mikkeli": (61.6886, 27.2723),
    "Pieksämäki": (62.3000, 27.1333),
    "Suonenjoki": (62.6167, 27.1333),
    "Keuruu": (62.2667, 24.7000),
    "Äänekoski": (62.6000, 25.7333),
    "Toivakka": (62.1000, 26.0833),
    "Luhanka": (61.8000, 25.7000),
    "Espoo": (60.2055, 24.6559),
    "Helsinki": (60.1699, 24.9384),
}


def resolve_event_location(event: dict) -> dict:
    """Resolve missing event coordinates from the event city."""

    event = {**event}
    location = {**(event.get("location") or {})}

    raw_lat = location.get("latitude")
    raw_lon = location.get("longitude")

    has_coordinates = (
        raw_lat is not None
        and raw_lon is not None
        and _is_number(raw_lat)
        and _is_number(raw_lon)
    )

    if has_coordinates:
        event["location"] = location
        event["locationStatus"] = "coordinates_available"
        event["needsGeocoding"] = False

        return event

    city = location.get("city")

    if city and city in CITY_COORDINATES:
        latitude, longitude = CITY_COORDINATES[city]

        location["latitude"] = latitude
        location["longitude"] = longitude

        event["location"] = location
        event["locationStatus"] = "city_resolved"
        event["needsGeocoding"] = False

        return event

    event["location"] = location
    event["locationStatus"] = "needs_geocoding"
    event["needsGeocoding"] = True

    return event


def filter_events_by_radius(
    events: list[dict],
    center_lat: float,
    center_lon: float,
    radius_km: float,
) -> list[dict]:
    """Keep events within the configured radius of the center."""

    results = []

    for event in events:
        location = event.get("location") or {}

        latitude = location.get("latitude")
        longitude = location.get("longitude")

        if not (
            _is_number(latitude)
            and _is_number(longitude)
        ):
            continue

        latitude = float(latitude)
        longitude = float(longitude)

        distance_km = _haversine_distance(
            center_lat,
            center_lon,
            latitude,
            longitude,
        )

        if distance_km <= radius_km:
            results.append({
                **event,
                "distanceKm": round(distance_km, 1),
            })

    return results


def _haversine_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Calculate the distance between two coordinates in kilometers."""

    earth_radius_km = 6371

    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)

    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(d_lon / 2) ** 2
    )

    return 2 * earth_radius_km * asin(sqrt(a))


def _is_number(value) -> bool:
    """Return whether a value can be converted to a finite number."""

    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False