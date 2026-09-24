"""Pydantic models for events exchanged through the API.

The models validate event structure at the API boundary. Domain functions
continue to operate on plain dictionaries, so validated events are converted
back with `model_dump(exclude_unset=True)`: only fields present in the input
are returned, and unknown fields are preserved.
"""

import logging

from pydantic import BaseModel, ConfigDict, ValidationError


logger = logging.getLogger(__name__)


class Location(BaseModel):
    """Event location, as produced by extraction and location resolution."""

    model_config = ConfigDict(
        extra="allow",
        # NaN/inf cannot be serialized into JSON responses.
        allow_inf_nan=False,
    )

    venue: str | None = None
    city: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class Event(BaseModel):
    """Event at any pipeline stage; stage-specific fields are optional."""

    model_config = ConfigDict(
        extra="allow",
        allow_inf_nan=False,
    )

    # Extraction
    name: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    time: str | None = None
    price: str | float | int | None = None
    location: Location | None = None
    description: str | None = None
    url: str | None = None
    sourceUrls: list[str] | None = None
    sourceType: str | None = None
    eventId: str | None = None

    # Date filtering
    occurrenceDate: str | None = None

    # Location resolution
    locationStatus: str | None = None
    needsGeocoding: bool | None = None

    # Radius filtering
    distanceKm: float | None = None


def validate_event(event: dict) -> dict:
    """Validate one event and return it as a dictionary.

    Raises pydantic.ValidationError for structurally invalid events.
    """

    return Event.model_validate(event).model_dump(
        exclude_unset=True
    )


def validate_events(events: list[dict]) -> list[dict]:
    """Validate events individually, skipping invalid ones.

    One malformed scraped event must not fail the whole batch, so invalid
    events are logged and dropped while valid events continue.
    """

    valid_events = []

    for index, event in enumerate(events):
        try:
            valid_events.append(
                validate_event(event)
            )
        except ValidationError as error:
            logger.warning(
                "Skipping invalid event at index %d: %s",
                index,
                _summarize(error),
            )

    skipped = len(events) - len(valid_events)

    if skipped:
        logger.warning(
            "Validated events: %d received, %d valid, %d skipped",
            len(events),
            len(valid_events),
            skipped,
        )

    return valid_events


def _summarize(error: ValidationError) -> str:
    """Return a compact, single-line description of validation errors."""

    return "; ".join(
        f"{'.'.join(str(part) for part in detail['loc'])}: {detail['msg']}"
        for detail in error.errors(include_url=False)
    )
