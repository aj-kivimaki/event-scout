# Event Scout

A Python + FastAPI event discovery service orchestrated by n8n.

Event Scout searches for concerts, live music, stand-up, comedy, cultural events, and other local events around a configurable location. It collects search results, fetches event pages, extracts structured event data, resolves locations, filters by distance and date, removes duplicates, and produces a weekly event digest.

The project is designed as a practical example of separating **workflow orchestration** from **application/domain logic**.

## Architecture

```text
                         ┌──────────────────────┐
                         │      n8n             │
                         │  Workflow orchestration│
                         └──────────┬───────────┘
                                    │ HTTP
                                    ▼
                         ┌──────────────────────┐
                         │   Python / FastAPI   │
                         │                      │
                         │ Config & validation  │
                         │ Date calculations    │
                         │ Search query logic   │
                         │ Event extraction     │
                         │ Location resolution  │
                         │ Radius filtering     │
                         │ Date filtering       │
                         │ Deduplication        │
                         └──────────────────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │ Search / Event pages │
                         └──────────────────────┘

                 n8n continues with presentation/output
                         │
                         ▼
                  Weekly event digest
```

n8n is responsible primarily for orchestration and external workflow steps. Python contains the reusable application logic.

## Main workflow

```text
Read Config File
      ↓
Extract Config Text
      ↓
Python — Build Search Context
      ↓
Python — Generate Search Queries
      ↓
Search Web — Tavily
      ↓
Flatten Search Results
      ↓
Deduplicate URLs
      ↓
Filter Event URLs
      ↓
Add Fetch Index
      ↓
Fetch Event Pages
      ↓
Python — Extract Event Data
      ↓
Python — Filter Events by Date
      ↓
Python — Resolve Event Locations
      ↓
Python — Filter Events by Radius
      ↓
Python — Deduplicate Events
      ↓
Prepare Event Data
      ↓
Group Events by Week
      ↓
Build Email HTML
      ↓
Send message
```

## Python application

The FastAPI service exposes the domain logic through HTTP endpoints.

### API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/config/parse` | Parse and validate YAML configuration |
| POST | `/dates/calculate` | Calculate the search date range |
| POST | `/search/context` | Build validated search context |
| POST | `/search/queries` | Generate discovery queries |
| POST | `/events/extract` | Extract events from HTML |
| POST | `/events/location` | Resolve an event location |
| POST | `/events/filter-radius` | Filter events by geographic radius |
| POST | `/events/filter-date` | Filter events by date |
| POST | `/events/deduplicate` | Merge duplicate events |

FastAPI also provides interactive API documentation:

```text
http://localhost:8000/docs
```

and:

```text
http://localhost:8000/redoc
```

## Project structure

```text
event-scout/
├── config/
│   ├── events.yaml
│   └── test-event-page.html
│
├── data/
│
├── n8n/
│   └── data/
│
├── prompts/
│
├── src/
│   ├── config/
│   │   ├── parser.py
│   │   └── schema.py
│   │
│   ├── event_digest/
│   │   ├── api.py
│   │   ├── dates.py
│   │   ├── deduplication.py
│   │   ├── extraction.py
│   │   ├── locations.py
│   │   ├── queries.py
│   │   └── search_context.py
│   │
│   └── ...
│
├── workflows/
│
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── requirements.txt
├── MVP.md
└── README.md
```

## Configuration

The event search is configured through YAML.

Example:

```yaml
id: w9spsn

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

The configuration is parsed with PyYAML and validated using Pydantic.

The date range is calculated dynamically from the configured lookahead period.

## Event extraction

Event pages are currently processed using two extraction strategies:

### JSON-LD

The extractor searches for:

```html
<script type="application/ld+json">
```

and extracts structured `Event` objects.

It supports JSON-LD structures including:

- direct event objects
- `@graph`
- nested `event` objects
- different JSON-LD event types ending in `Event`

### Allevents

A separate parser handles Allevents listing-page data.

The extractor also:

- normalizes dates
- extracts event times
- handles 12-hour and 24-hour time formats
- handles Finnish `klo` / `kl.` formats
- extracts venue and address information
- extracts coordinates where available
- preserves source URLs

## Location handling

Events can receive coordinates in two ways:

1. Coordinates already present in the source data
2. Known city coordinates resolved by the application

Events are then filtered using geographic distance calculated with the Haversine formula.

The configured center and radius determine which events are retained.

## Deduplication

Multiple sources can describe the same event.

The deduplication stage compares:

- normalized event/artist name
- event date
- geographic distance when coordinates are available

Duplicate events are merged while preserving useful source information such as:

- source URLs
- descriptions
- venue
- city
- address
- coordinates
- distance from the search center

## Docker

The project runs n8n and the Python API as separate Docker services on a shared Docker network.

```text
n8n
 └── http://python-api:8000

python-api
 └── FastAPI / Uvicorn
```

From the host machine, the services are available at:

```text
n8n:        http://localhost:5679
FastAPI:    http://localhost:8000
FastAPI UI: http://localhost:8000/docs
```

The Docker network allows n8n to communicate with the API using:

```text
http://python-api:8000
```

rather than `localhost`.

## Development

### Requirements

- Docker
- Docker Compose
- Python 3.10+
- Git

### Python environment

Create the virtual environment:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Running the application

Start the complete stack:

```bash
docker compose up -d
```

Or use the Makefile:

```bash
make up
```

After changing Python source code, rebuild the API image:

```bash
make rebuild
```

View API logs:

```bash
make logs
```

Stop the stack:

```bash
make down
```

## Testing

A saved event-page fixture is available at:

```text
config/test-event-page.html
```

It can be used to test the extraction workflow without repeatedly fetching live event pages.

The extraction pipeline has been verified against the fixture and the full n8n workflow has been run end-to-end.

A representative verified flow is:

```text
181 extracted events
        ↓
71 events after date filtering
        ↓
71 after location resolution
        ↓
8 within configured radius
        ↓
6 after deduplication
```

## Technology

- **Python**
- **FastAPI**
- **Pydantic**
- **PyYAML**
- **Uvicorn**
- **Docker**
- **Docker Compose**
- **n8n**
- **Tavily Search API**

## Design goals

The project intentionally separates responsibilities:

### n8n

Used for:

- workflow orchestration
- file handling
- external search
- HTTP requests
- fetching event pages
- presentation
- email delivery

### Python

Used for:

- configuration validation
- date calculations
- search-query generation
- event extraction
- location resolution
- geographic filtering
- date filtering
- event deduplication

This keeps business logic testable and reusable instead of embedding the core application behavior inside large n8n Code nodes.

## Status

The core event discovery workflow is functional and runs end-to-end through Docker and n8n.

The next development focus is automated Python tests and further hardening of the application/API boundary.
