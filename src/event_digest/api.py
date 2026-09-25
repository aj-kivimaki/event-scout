import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Annotated

import yaml
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, ValidationError

from src.config.parser import parse_config
from src.event_digest.dates import (
    calculate_date_range,
    filter_events_by_date,
    max_lookahead_weeks,
)
from src.event_digest.deduplication import deduplicate_events
from src.event_digest.extraction import extract_event_data
from src.event_digest.locations import (
    filter_events_by_radius,
    resolve_event_location,
)
from src.event_digest.models import (
    validate_event,
    validate_events,
)
from src.event_digest.queries import generate_search_queries
from src.event_digest.search_context import build_search_context


app = FastAPI(title="Event Scout API")


class ConfigRequest(BaseModel):
    yaml_text: str


class EventExtractionRequest(BaseModel):
    html: str
    page_url: str | None = None


class EventLocationRequest(BaseModel):
    event: dict


class RadiusFilterRequest(BaseModel):
    events: list[dict]
    center_lat: float
    center_lon: float
    radius_km: float


class DateFilterRequest(BaseModel):
    events: list[dict]
    start_date: str
    end_date: str


class DeduplicationRequest(BaseModel):
    events: list[dict]


CONFIG_ERROR_LOCATION = ["body", "yaml_text"]
EVENT_ERROR_LOCATION = ["body", "event"]


def validation_error_details(
    error: ValidationError,
    location: list[str],
) -> list[dict]:
    """Format a Pydantic error like FastAPI's request-validation errors.

    Error locations are prefixed with the request field that was validated.
    """

    details = json.loads(error.json(include_url=False))

    return [
        {
            **detail,
            "loc": [
                *location,
                *detail["loc"],
            ],
        }
        for detail in details
    ]


@contextmanager
def config_errors_as_http() -> Iterator[None]:
    """Report invalid configuration as a 422 client error.

    Errors follow FastAPI's request-validation format, with locations
    prefixed by the request field that contains the YAML configuration.
    """

    try:
        yield
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=validation_error_details(
                error,
                CONFIG_ERROR_LOCATION,
            ),
        ) from error
    except yaml.YAMLError as error:
        detail = {
            "type": "yaml_invalid",
            "loc": CONFIG_ERROR_LOCATION,
            "msg": f"Invalid YAML: {error}",
        }

        mark = getattr(error, "problem_mark", None)

        if mark is not None:
            detail["ctx"] = {
                "line": mark.line + 1,
                "column": mark.column + 1,
            }

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[detail],
        ) from error
    except ValueError as error:
        # Raised by parse_config() for YAML that is not a mapping.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[
                {
                    "type": "config_invalid",
                    "loc": CONFIG_ERROR_LOCATION,
                    "msg": str(error),
                }
            ],
        ) from error


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/config/parse")
def parse_config_endpoint(request: ConfigRequest):
    with config_errors_as_http():
        config = parse_config(request.yaml_text)

    return config.model_dump()


@app.post("/dates/calculate")
def calculate_dates(
    lookahead_weeks: Annotated[int, Query(gt=0)],
):
    max_weeks = max_lookahead_weeks()

    if lookahead_weeks > max_weeks:
        # Same format as FastAPI's own query-parameter validation errors.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[
                {
                    "type": "less_than_equal",
                    "loc": ["query", "lookahead_weeks"],
                    "msg": f"Input should be less than or equal to {max_weeks}",
                    "input": str(lookahead_weeks),
                    "ctx": {"le": max_weeks},
                }
            ],
        )

    start_date, end_date = calculate_date_range(
        lookahead_weeks
    )

    return {
        "start_date": start_date,
        "end_date": end_date,
    }


@app.post("/search/context")
def create_search_context(request: ConfigRequest):
    with config_errors_as_http():
        context = build_search_context(request.yaml_text)

    return {
        "config": context["config"].model_dump(),
        "start_date": context["start_date"],
        "end_date": context["end_date"],
    }


@app.post("/search/queries")
def create_search_queries(request: ConfigRequest):
    with config_errors_as_http():
        context = build_search_context(request.yaml_text)

    queries = generate_search_queries(
        start_date=str(context["start_date"]),
        end_date=str(context["end_date"]),
    )

    return [
        {
            **asdict(query),
            "start_date": str(context["start_date"]),
            "end_date": str(context["end_date"]),
        }
        for query in queries
    ]


@app.post("/events/extract")
def extract_events(request: EventExtractionRequest):
    return extract_event_data(
        html=request.html,
        page_url=request.page_url,
    )


@app.post("/events/location")
def resolve_event_location_endpoint(
    request: EventLocationRequest,
):
    # A single event has nothing to skip, so an invalid event is a
    # client error.
    try:
        event = validate_event(request.event)
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=validation_error_details(
                error,
                EVENT_ERROR_LOCATION,
            ),
        ) from error

    return resolve_event_location(event)


@app.post("/events/filter-radius")
def filter_events_radius_endpoint(
    request: RadiusFilterRequest,
):
    return filter_events_by_radius(
        events=validate_events(request.events),
        center_lat=request.center_lat,
        center_lon=request.center_lon,
        radius_km=request.radius_km,
    )


@app.post("/events/filter-date")
def filter_events_date_endpoint(
    request: DateFilterRequest,
):
    return filter_events_by_date(
        events=validate_events(request.events),
        start_date=request.start_date,
        end_date=request.end_date,
    )


@app.post("/events/deduplicate")
def deduplicate_events_endpoint(
    request: DeduplicationRequest,
):
    return deduplicate_events(
        validate_events(request.events)
    )