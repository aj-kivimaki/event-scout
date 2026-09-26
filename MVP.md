# Event Scout — MVP

## Goal

Build an event discovery pipeline that finds relevant events happening during the configured search period and produces a chronological HTML digest.

The system discovers concerts, live music, stand-up, comedy and similar cultural events around Joutsa, Finland.

The original goal was to run the workflow automatically every Sunday. The current workflow is manual and inactive.

## Core Requirements

- Look ahead a configurable number of weeks (3 by default).
- Generate discovery queries for multiple event sources.
- Fetch event pages through the n8n workflow.
- Find:
  - Concerts
  - Live music
  - Stand-up
  - Comedy
  - Similar cultural/evening events
- Extract and normalize event information.
- Filter events by date.
- Resolve event locations where possible.
- Filter events by distance from a configured center.
- Remove duplicate events.
- Generate an HTML digest grouped by week.
- Preserve links to the original event pages.

## Architecture

```text
Internet / Event Sources
          |
          v
         n8n
          |
     Search + Fetch
          |
          | HTTP
          v
    Python / FastAPI
          |
    Extract events
          |
    Normalize data
          |
    Filter by date
          |
    Resolve locations
          |
    Filter by radius
          |
      Deduplicate
          |
          v
         n8n
          |
    Group by week
          |
    Build HTML digest
```

n8n is responsible for workflow orchestration and external I/O. Python contains the event-processing logic and exposes it through FastAPI.

## Python Application

Python contains:

- YAML configuration parsing and validation
- Date-range calculation
- Search-query generation
- JSON-LD event extraction
- Allevents extraction
- Date and time normalization
- Date filtering
- Location resolution
- Radius filtering
- Event deduplication
- Event and request validation

FastAPI exposes the application capabilities to n8n and provides the validation boundary for requests and event data.

## Configuration

Preferences are kept outside the workflow in `config/events.yaml`:

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

The configuration is parsed with PyYAML and validated with Pydantic.

| Field | Current role |
|---|---|
| `center.latitude`, `center.longitude` | Center point for radius filtering |
| `center.name` | Validated informational field |
| `radius_km` | Radius filter |
| `lookahead_weeks` | Search period and digest length |
| `categories` | Validated but not currently used for search generation or filtering |

The searched cities, venues and sources are currently hard-coded in Python for the Joutsa region.

## Event Data

The normalized event model can contain:

```text
name
startDate
endDate
time
location
description
price
url
sourceUrls
sourceType
eventId
occurrenceDate
locationStatus
needsGeocoding
distanceKm
```

Additional source fields can also be preserved during processing.

## Email / Digest

n8n groups processed events by week and builds the HTML digest.

Email delivery is currently disconnected from the workflow. Gmail can be connected later when live delivery is enabled.

## MVP Progress

1. Create standalone project repository. ✓
2. Set up n8n with Docker. ✓
3. Create the n8n workflow with a manual trigger. ✓
4. Implement discovery search-query generation. ✓
5. Implement event-page fetching in n8n. ✓
6. Extract and normalize event data. ✓
7. Deduplicate events. ✓
8. Filter by date and location. ✓
9. Separate application logic into Python/FastAPI. ✓
10. Generate HTML digest. ✓
11. Run the Python pipeline and n8n workflow end-to-end. ✓
12. Add automated Python tests and CI. ✓
13. Validate API requests, events and configuration. ✓
14. Export the workflow into the repository. ✓
15. Document the current architecture and limitations. ✓
16. Pin Python dependencies. ✓

### Not completed

- Scheduled weekly execution.
- Live Tavily search connection.
- Gmail delivery connection.
- Persistence/database.
- Authentication.
- Deployment.
- Automatic geocoding.
- Configurable search geography.
- Using `categories` to control search generation/filtering.

## Status

The Python/FastAPI application, validation, event-processing pipeline, automated tests, CI, Docker setup and n8n workflow are implemented.

The workflow in `workflows/Weekly Event Scout.json` is currently manual and inactive. The live Tavily search and Gmail paths are disconnected. A test-data branch uses the saved `config/test-event-page.html` so the pipeline can be exercised without live search or email credentials.

The current implementation is considered a completed MVP for its defined scope.

## Deliberately Excluded

### Local LLM / Ollama

The original concept included a local LLM for classification, cleanup and summarization.

This is not part of the current architecture.

The current implementation performs event extraction, normalization, filtering and deduplication deterministically in Python.

An LLM could be added later if a concrete use case emerges where deterministic processing is insufficient.

## Future Ideas

- Scheduled weekly execution.
- Reconnect live Tavily search.
- Reconnect Gmail delivery.
- Use the configured categories in search generation or filtering.
- Configurable search geography and automatic geocoding.
- Optional LLM-based event classification or summarization.
- Personal event preferences.
- Track previously seen events.
- Avoid sending the same event repeatedly.
- Store events in a database.
- Add a web UI for browsing collected events.
- Track event history and attendance decisions.
