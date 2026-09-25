# Event Scout — MVP

## Goal

Research the internet for relevant events happening during the next three weeks and produce a chronological email digest.

The system helps discover concerts, live music, stand-up, comedy and similar cultural/evening events around Joutsa, Finland.

The original goal was to run the workflow automatically every Sunday. The current workflow is run manually (see [Status](#status)).

## Core Requirements

- Look ahead a configurable number of weeks (3 by default).
- Search multiple internet sources.
- Find:
  - Concerts
  - Live music
  - Stand-up
  - Comedy
  - Similar cultural/evening events
- Filter events by distance from a configured center.
- Remove duplicate events.
- Normalize event information.
- Generate a chronological email digest grouped by week.
- Include a link to the original event page for every event.

## Architecture

```text
Internet / Event Sources
          ↓
         n8n
          ↓
     Search + Fetch
          ↓
    Python / FastAPI
          ↓
    Extract events
          ↓
    Normalize data
          ↓
   Date / location filter
          ↓
      Deduplicate
          ↓
         n8n
          ↓
     Generate digest
          ↓
         Email
```

## Python Application

Python contains the event-processing logic:

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

FastAPI exposes these capabilities to the n8n workflow, with request and event validation at the API boundary.

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

`center`, `radius_km` and `lookahead_weeks` control the radius filter, the search period and the digest weeks. `categories` is validated but not yet used. The searched cities, venues and sources are hard-coded in Python for the Joutsa region.

## Event Data

Events contain approximately:

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
```

## Email

Events are organized chronologically and grouped by week in an HTML digest built by n8n.

## MVP Progress

1. Create standalone project repository. ✓
2. Set up n8n with Docker. ✓
3. Create the n8n workflow (manual trigger). ✓
4. Implement web/event-source searches. ✓
5. Extract and normalize event data. ✓
6. Deduplicate events. ✓
7. Filter by date and location. ✓
8. Separate application logic into Python/FastAPI. ✓
9. Generate HTML email. ✓
10. Send test emails. ✓
11. Run the complete workflow end-to-end. ✓
12. Add automated Python tests and CI. ✓
13. Validate API requests, events and configuration. ✓

Not completed:

- Scheduled weekly run. The workflow has no schedule trigger and is inactive.

## Status

The Python/FastAPI pipeline, validation and automated tests (pytest, run in GitHub Actions) are implemented.

The n8n workflow in `workflows/Weekly Event Scout.json` is manual and inactive. The live search (Tavily) and email (Gmail) paths are currently disconnected; a test-data branch runs the pipeline on a saved event page.

## Deliberately Excluded

### Local LLM / Ollama

The original MVP included a local LLM for classification, cleanup and summarization.

This was removed from the current architecture.

The current implementation performs deterministic event extraction, normalization, filtering and deduplication in Python instead.

This keeps the core event pipeline simpler, faster and more predictable.

An LLM can still be added later if there is a concrete use case where deterministic processing is insufficient.

## Future Ideas

- Scheduled weekly run.
- Use the configured categories in searches.
- Configurable search geography and geocoding.
- Add an LLM for optional event classification or summarization.
- Personal event preferences.
- Track previously seen events.
- Avoid sending the same event repeatedly.
- Add a "maybe interesting" category based on user-defined preferences.
- Store events in a database.
- Web UI for browsing collected events.
- Track event history and attendance decisions.
