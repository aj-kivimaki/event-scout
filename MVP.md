# Event Scout — MVP

## Goal

Every Sunday, automatically research the internet for relevant events happening during the next three weeks and send a chronological email digest.

The system helps discover concerts, live music, stand-up, comedy and similar cultural/evening events in the configured geographical area.

## Core Requirements

- Run automatically every Sunday.
- Look ahead exactly 3 weeks.
- Search multiple internet sources.
- Find:
  - Concerts
  - Live music
  - Stand-up
  - Comedy
  - Similar cultural/evening events
- Filter events by configured geographical area.
- Remove duplicate events.
- Normalize event information.
- Generate a chronological email digest.
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

Python contains the core event-processing logic.

Responsibilities include:

- YAML configuration parsing and validation
- Date-range calculation
- Search-query generation
- JSON-LD event extraction
- Allevents extraction
- Date and time normalization
- Location resolution
- Geographic filtering
- Date filtering
- Event deduplication

FastAPI exposes these capabilities to the n8n workflow.

## Configuration

Keep preferences outside the workflow so they can easily be changed.

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

## Event Data

Events should ultimately contain approximately:

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

Organize events chronologically and group them by week.

```text
EVENT SCOUT

28 Sep – 18 Oct

WEEK 1

Sunday 28 Sep

  20:00 — Artist
  Venue, City
  Concert
  €25

  Event page

Monday 29 Sep

  ...

WEEK 2

...

SUMMARY

Concerts: X
Stand-up: X
Other: X
```

## MVP Progress

1. Create standalone project repository. ✓
2. Set up n8n with Docker. ✓
3. Create scheduled workflow. ✓
4. Implement web/event-source searches. ✓
5. Extract and normalize event data. ✓
6. Deduplicate events. ✓
7. Filter by date and location. ✓
8. Separate application logic into Python/FastAPI. ✓
9. Generate HTML email. ✓
10. Send test emails. ✓
11. Run the complete workflow end-to-end. ✓
12. Add automated Python tests. Next.

## Deliberately Excluded

### Local LLM / Ollama

The original MVP included a local LLM for classification, cleanup and summarization.

This was removed from the current architecture.

The current implementation performs deterministic event extraction, normalization, filtering and deduplication in Python instead.

This keeps the core event pipeline simpler, faster and more predictable.

An LLM can still be added later if there is a concrete use case where deterministic processing is insufficient.

## Future Ideas

- Add an LLM for optional event classification or summarization.
- Personal event preferences.
- Track previously seen events.
- Avoid sending the same event repeatedly.
- Add a "maybe interesting" category based on user-defined preferences.
- Store events in a database.
- Web UI for browsing collected events.
- Add more cities or change the search radius.
- Track event history and attendance decisions.
