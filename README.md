# Event Scout

A Python + FastAPI event discovery pipeline orchestrated by n8n.

Event Scout looks for concerts, live music, stand-up, comedy and other cultural events around Joutsa, Finland. It generates search queries, fetches event pages, extracts structured event data, resolves locations, filters by date and distance, removes duplicates, and builds an HTML digest grouped by week.

The project is a practical example of separating **workflow orchestration** (n8n) from **application logic** (Python), so that the logic is validated at an API boundary and covered by automated tests.

## Architecture

```text
Internet / event pages
          ↓
         n8n  ── search (Tavily) + fetch pages
          ↓  HTTP
   Python / FastAPI
          ↓
    Extract events
          ↓
   Filter by date
          ↓
   Resolve locations
          ↓
   Filter by radius
          ↓
      Deduplicate
          ↓
         n8n  ── group by week, build HTML digest, email (Gmail)
```

n8n is responsible for orchestration and external I/O: reading the configuration file, calling the search API, fetching pages, presenting the digest and sending email. Python contains the application logic and exposes it to n8n through HTTP endpoints.

## n8n workflow

The workflow is stored in [`workflows/Weekly Event Scout.json`](workflows/Weekly%20Event%20Scout.json) and is imported into n8n manually.

```text
Manual Trigger
  ├─ Read Config File → Extract Config Text
  │    → Python — Build Search Context
  │    → Python — Generate Search Queries
  │    ⋯ (disconnected) ⋯
  │    Search Web — Tavily → Flatten Search Results → Deduplicate URLs
  │    → Filter Event URLs → Add Fetch Index → Fetch Event Pages ─┐
  │                                                               ↓
  └─ Read Test Data → Extract from File ──────→ Python — Extract Event Data
                                                → Python — Filter Events by Date
                                                → Python — Resolve Event Locations
                                                → Python — Filter Events by Radius
                                                → Python — Deduplicate Events
                                                → Prepare Event Data
                                                → Group Events by Week
                                                → Build Email HTML
                                                ⋯ (disconnected) ⋯
                                                Send a message (Gmail)
```

Current state of the workflow in the repository:

- It is **manual and inactive**; there is no schedule trigger.
- The live search path is **disconnected** between query generation and Tavily. Live search requires a Tavily API key, configured in n8n as a Bearer Auth credential.
- Email delivery is **disconnected** after the HTML digest is built. Sending requires a Gmail OAuth2 credential in n8n.
- A **test-data branch** reads the saved page `config/test-event-page.html` so the Python pipeline and digest can be run without live searches. When Build Search Context has not run, the date and radius nodes fall back to fixed test values (2026-09-28 to 2026-10-18, Joutsa, 100 km).

To run the live pipeline, create the two credentials in n8n and reconnect the disconnected edges.

## Python application

### API

| Method | Endpoint | Purpose | Used by the workflow |
|---|---|---|---|
| GET | `/health` | Health check | |
| POST | `/config/parse` | Parse and validate YAML configuration | |
| POST | `/dates/calculate` | Calculate the search date range | |
| POST | `/search/context` | Validated configuration and date range | ✓ |
| POST | `/search/queries` | Generate discovery search queries | ✓ |
| POST | `/events/extract` | Extract events from an HTML page | ✓ |
| POST | `/events/filter-date` | Keep events within the date range | ✓ |
| POST | `/events/location` | Resolve coordinates for one event | ✓ |
| POST | `/events/filter-radius` | Keep events within the radius | ✓ |
| POST | `/events/deduplicate` | Merge duplicate events | ✓ |

Interactive API documentation is available at `http://localhost:8000/docs` and `http://localhost:8000/redoc`.

### Validation and errors

- Requests are validated with Pydantic. Invalid requests and invalid configuration return `422` in FastAPI's standard validation-error format.
- Events are validated with the `Event`/`Location` models in `models.py`. Batch endpoints skip and log individual invalid events so that one malformed scraped event does not fail the whole batch; `/events/location` returns `422` for an invalid event.
- Coordinates, radius and dates are range-checked, and non-finite numbers (`NaN`, `Infinity`) are rejected.

### Event extraction

Two strategies are used:

- **JSON-LD** — `<script type="application/ld+json">` blocks, including `@graph`, nested `event` objects, lists, and any `@type` ending in `Event`.
- **Allevents** — event records embedded in Allevents listing pages.

The extractor normalizes dates, extracts times (12-hour, 24-hour and Finnish `klo` / `kl.` formats), venue, city, address and coordinates, and preserves source URLs. Malformed coordinates are ignored per event.

### Date filtering

The search period is a whole number of Monday–Sunday weeks starting from the next Monday (Helsinki time). Events are kept when their start date is in the period. Long-running events are also kept for dates mentioned in their description (ISO dates and `Month D, YYYY`) that fall within the period.

### Location handling

Events receive coordinates in two ways:

1. Coordinates present in the source data.
2. A hard-coded table of city coordinates for the Joutsa region (and Helsinki/Espoo).

Distance from the configured center is calculated with the Haversine formula. There is no geocoding: events without coordinates or a known city are marked `needs_geocoding` and are excluded by the radius filter.

### Deduplication

Events are treated as duplicates when their normalized event/artist name and date match, and, when both have coordinates, they are within 5 km of each other. Duplicates are merged, keeping all source URLs and filling in missing description, venue, city, address, coordinates and distance.

## Configuration

The search is configured in [`config/events.yaml`](config/events.yaml):

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

The file is parsed with PyYAML and validated with Pydantic (`src/config/schema.py`).

| Field | Effect |
|---|---|
| `center.latitude`, `center.longitude` | Center point for the radius filter |
| `center.name` | Validated; informational |
| `radius_km` | Radius filter distance (must be positive) |
| `lookahead_weeks` | Number of weeks in the search period and the digest |
| `categories` | Validated (at least one), but **not currently used** to generate or filter searches |

The search geography is **hard-coded in Python**: the cities, venues, event aggregators and official calendars used for search queries (`queries.py`) and the city coordinate table (`locations.py`) cover the Joutsa region. Changing `center` or `radius_km` changes the radius filter, not which places are searched.

## Project structure

```text
event-scout/
├── .github/workflows/tests.yml   # CI: pytest on push and pull request
├── config/
│   ├── events.yaml               # search configuration
│   ├── test-event-page.html      # saved event page (n8n test branch and tests)
│   ├── fetch-event-pages.json    # captured n8n data from development
│   └── radius-events.json        # captured n8n data from development
├── n8n/data/                     # local n8n state (gitignored)
├── src/
│   ├── config/
│   │   ├── parser.py             # YAML parsing
│   │   └── schema.py             # configuration models
│   └── event_digest/
│       ├── api.py                # FastAPI endpoints and request models
│       ├── models.py             # Event/Location validation models
│       ├── errors.py             # JSON-safe validation-error handling
│       ├── search_context.py     # configuration + date range
│       ├── queries.py            # search query generation
│       ├── extraction.py         # JSON-LD and Allevents extraction
│       ├── dates.py              # date range and date filtering
│       ├── locations.py          # location resolution and radius filter
│       └── deduplication.py      # duplicate merging
├── tests/
│   ├── fixtures/                 # saved Allevents listing pages
│   └── test_*.py
├── workflows/
│   └── Weekly Event Scout.json   # n8n workflow export
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── pyproject.toml                # pytest configuration
├── requirements.txt
├── requirements-dev.txt
├── MVP.md
└── README.md
```

## Running

### Requirements

- Docker and Docker Compose
- Python 3.10 (the version used by the Docker image and CI) for local development and tests

### Docker

n8n and the Python API run as separate services on a shared Docker network:

```bash
docker compose up -d
```

| Service | Host URL | From n8n |
|---|---|---|
| n8n | `http://localhost:5679` | |
| FastAPI | `http://localhost:8000` | `http://python-api:8000` |

The `config/` directory is mounted into the n8n container at `/home/node/.n8n-files/config`.

After changing Python source code, rebuild and restart the API container:

```bash
make rebuild
```

### Local environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Testing

Tests use pytest and run with:

```bash
make test
```

(equivalent to `python -m pytest`). The same test suite runs in GitHub Actions on every push and pull request.

The suite covers:

- configuration parsing and validation
- date range calculation and date filtering
- event extraction, including regression tests against saved real pages (JamBase, Allevents, ConcertArchives)
- location resolution and radius filtering
- deduplication
- event models and validation-error handling
- the API boundary, including request validation, error responses, and a full pipeline run through the API in the same order as the n8n workflow

Tests that document known limitations are kept in clearly marked "known issues" sections.

With the search period 2026-09-28 to 2026-10-18 and a 100 km radius around Joutsa, the saved JamBase page `config/test-event-page.html` produces:

```text
181 extracted events
        ↓
 71 after date filtering
        ↓
  8 within the radius
        ↓
  6 after deduplication
```

## Technology

Python, FastAPI, Pydantic, PyYAML, Uvicorn, pytest, Docker, Docker Compose, GitHub Actions, n8n, Tavily Search API, Gmail.

## Status

The Python/FastAPI pipeline, API validation and automated tests are implemented. The n8n workflow has been run end-to-end, and is currently kept manual and inactive, with the live search (Tavily) and email (Gmail) paths disconnected. The saved test page can be used to run the pipeline without them.

Not implemented: scheduled automation, persistence, authentication, deployment, geocoding, and configurable search geography. See [MVP.md](MVP.md) for scope and future ideas.
