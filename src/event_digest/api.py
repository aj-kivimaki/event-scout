from dataclasses import asdict

from fastapi import FastAPI
from pydantic import BaseModel

from src.config.parser import parse_config
from src.event_digest.dates import (
    calculate_date_range,
    filter_events_by_date,
)
from src.event_digest.deduplication import deduplicate_events
from src.event_digest.extraction import extract_event_data
from src.event_digest.locations import (
    filter_events_by_radius,
    resolve_event_location,
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


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/config/parse")
def parse_config_endpoint(request: ConfigRequest):
    config = parse_config(request.yaml_text)

    return config.model_dump()


@app.post("/dates/calculate")
def calculate_dates(lookahead_weeks: int):
    start_date, end_date = calculate_date_range(
        lookahead_weeks
    )

    return {
        "start_date": start_date,
        "end_date": end_date,
    }


@app.post("/search/context")
def create_search_context(request: ConfigRequest):
    context = build_search_context(request.yaml_text)

    return {
        "config": context["config"].model_dump(),
        "start_date": context["start_date"],
        "end_date": context["end_date"],
    }


@app.post("/search/queries")
def create_search_queries(request: ConfigRequest):
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
    return resolve_event_location(request.event)


@app.post("/events/filter-radius")
def filter_events_radius_endpoint(
    request: RadiusFilterRequest,
):
    return filter_events_by_radius(
        events=request.events,
        center_lat=request.center_lat,
        center_lon=request.center_lon,
        radius_km=request.radius_km,
    )


@app.post("/events/filter-date")
def filter_events_date_endpoint(
    request: DateFilterRequest,
):
    return filter_events_by_date(
        events=request.events,
        start_date=request.start_date,
        end_date=request.end_date,
    )


@app.post("/events/deduplicate")
def deduplicate_events_endpoint(
    request: DeduplicationRequest,
):
    return deduplicate_events(request.events)