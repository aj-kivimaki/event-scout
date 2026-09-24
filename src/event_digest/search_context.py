from src.config.parser import parse_config
from src.event_digest.dates import calculate_date_range


def build_search_context(yaml_text: str) -> dict:
    """Build the validated configuration and date range for an event search."""

    config = parse_config(yaml_text)

    start_date, end_date = calculate_date_range(
        config.lookahead_weeks
    )

    return {
        "config": config,
        "start_date": start_date,
        "end_date": end_date,
    }