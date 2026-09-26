# Event Scout

A Python + FastAPI event discovery pipeline orchestrated by n8n.

Event Scout finds concerts, live music, stand-up, comedy, and other cultural events around Joutsa, Finland. It generates search queries, fetches event pages, extracts structured event data, resolves locations, filters events by date and distance, removes duplicates, and builds an HTML digest grouped by week.

The project demonstrates a separation between **workflow orchestration** (n8n) and **application logic** (Python), with a validated HTTP API boundary and automated tests.

## Architecture

```text
Event sources
     |
     v
    n8n
 search + fetch
     |
     | HTTP
     v
Python / FastAPI
     |
     +--> Extract events
     |
     +--> Filter by date
     |
     +--> Resolve locations
     |
     +--> Filter by radius
     |
     +--> Deduplicate
     |
     v
    n8n
 group by week
 build HTML digest
     |
     v
  Gmail (optional)
```

n8n handles workflow orchestration and external I/O. Python contains the application logic and exposes it through FastAPI endpoints.

## Current workflow

The workflow is stored in [`workflows/Weekly Event Scout.json`](workflows/Weekly%20Event%20Scout.json).

It is currently **manual and inactive**. The repository contains a repeatable test-data path so the Python pipeline can be exercised without live search or email credentials.

The live Tavily search path and Gmail delivery path are intentionally disconnected in the current workflow.

## Python API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/config/parse` | Parse and validate YAML configuration |
| `POST` | `/dates/calculate` | Calculate the search date range |
| `POST` | `/search/context` | Validate configuration and calculate dates |
| `POST` | `/search/queries` | Generate discovery search queries |
| `POST` | `/events/extract` | Extract events from HTML |
| `POST` | `/events/filter-date` | Filter events by date |
| `POST` | `/events/location` | Resolve coordinates for an event |
| `POST` | `/events/filter-radius` | Filter events by distance |
| `POST` | `/events/deduplicate` | Merge duplicate events |

Interactive API documentation is available at:

- `http://localhost:8000/docs`
- `http://localhost:8000/redoc`

## Data processing

### Extraction

The extractor supports:

- JSON-LD event data, including `@graph`, nested event objects, lists, and event types ending in `Event`
- Allevents listing pages
- 12-hour and 24-hour time formats
- Finnish `klo` / `kl.` time formats
- venue, city, address, coordinates, and source URLs

Malformed coordinates are ignored per event rather than failing the entire batch.

### Date filtering

The search period consists of whole Monday–Sunday weeks starting from the next Monday in Helsinki time.

Events are kept when their start date falls within the period. Long-running events can also be retained when matching dates are found in their descriptions.

### Location handling

Coordinates come from:

1. Coordinates present in the source data.
2. A hard-coded city coordinate table covering the Joutsa region and Helsinki/Espoo.

Distance is calculated using the Haversine formula.

There is currently no automatic geocoding. Events without coordinates or a known city are marked as needing geocoding and excluded by the radius filter.

### Deduplication

Events are considered duplicates when their normalized event/artist name and date match and, when both have coordinates, they are within 5 km of each other.

Duplicate records are merged while preserving source URLs and filling missing event information where possible.

## Configuration

Configuration is stored in [`config/events.yaml`](config/events.yaml):

```yaml
center:
  name: Joutsa
  latitude: 61.742667
  longitude: 26.112972
radius_km: 100
lookahead_weeks: 3
categories:
  - concert
  - live_music
  - stand_up
  - comedy
  - cultural
```

Configuration is parsed with PyYAML and validated with Pydantic.

| Field | Effect |
|---|---|
| `center.latitude`, `center.longitude` | Center point for radius filtering |
| `center.name` | Validated informational field |
| `radius_km` | Radius filter distance |
| `lookahead_weeks` | Search period and digest length |
| `categories` | Validated but not currently used for search generation or filtering |

The search geography is currently hard-coded in Python. Changing the configured center or radius changes radius filtering, but does not change which cities, venues, or sources are searched.

## Validation and error handling

Pydantic models validate API requests and configuration.

The API validates:

- latitude and longitude ranges
- positive radius values
- date ranges
- finite numeric values
- event and location structures

Batch processing skips and logs individual malformed events instead of failing the complete batch.

## Project structure

```text
event-scout/
├── .github/
│   └── workflows/
│       └── tests.yml              # GitHub Actions CI
├── config/
│   ├── events.yaml                # Search configuration
│   └── test-event-page.html       # Saved page for repeatable testing
├── n8n/
│   └── data/                      # Local n8n state (gitignored)
├── src/
│   ├── config/
│   │   ├── parser.py              # YAML parsing
│   │   └── schema.py              # Configuration models
│   └── event_digest/
│       ├── api.py                 # FastAPI endpoints and request models
│       ├── models.py              # Event and Location models
│       ├── errors.py              # Validation-error handling
│       ├── search_context.py      # Configuration + date range
│       ├── queries.py             # Search query generation
│       ├── extraction.py          # JSON-LD and Allevents extraction
│       ├── dates.py               # Date calculation and filtering
│       ├── locations.py            # Location resolution and radius filtering
│       └── deduplication.py       # Duplicate merging
├── tests/
│   ├── fixtures/                  # Saved event pages
│   └── test_*.py
├── workflows/
│   └── Weekly Event Scout.json    # n8n workflow export
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── MVP.md
└── README.md
```

## Running locally

### Requirements

- Docker and Docker Compose
- Python 3.10

### Start the services

```bash
docker compose up -d
```

| Service | Host | n8n |
|---|---|---|
| n8n | `http://localhost:5679` | — |
| FastAPI | `http://localhost:8000` | `http://python-api:8000` |

The `config/` directory is mounted into the n8n container at `/home/node/.n8n-files/config`.

After changing Python source code:

```bash
make rebuild
```

### Local Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Testing

Run the complete test suite with:

```bash
make test
```

The same suite runs in GitHub Actions on every push and pull request.

The tests cover:

- configuration parsing and validation
- date calculation and filtering
- event extraction
- regression cases using saved real event pages
- location resolution and radius filtering
- deduplication
- Pydantic models
- API validation and error handling
- the complete API pipeline in the same order as the n8n workflow

For the current saved JamBase test page, using a 100 km radius around Joutsa and the period 2026-09-28 to 2026-10-18:

```text
181 extracted events
        |
        v
71 after date filtering
        |
        v
8 within the radius
        |
        v
6 after deduplication
```

## Technology

- Python 3.10
- FastAPI
- Pydantic
- PyYAML
- Uvicorn
- pytest
- Docker / Docker Compose
- GitHub Actions
- n8n
- Tavily Search API
- Gmail

## Status

The Python/FastAPI application, API validation, event-processing pipeline, automated tests, Docker setup, CI, and n8n workflow are implemented.

The current workflow is intentionally kept manual and inactive. Live Tavily search and Gmail delivery are disconnected, while the saved test page provides a repeatable local test path.

### Not currently implemented

- Scheduled automation
- Persistence/database
- Authentication
- Deployment
- Automatic geocoding
- Configurable search geography
- Using `categories` to control search generation/filtering

These are potential future extensions rather than requirements of the current MVP.
