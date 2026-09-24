import yaml

from src.config.schema import EventScoutConfig


def parse_config(yaml_text: str) -> EventScoutConfig:
    """Parse and validate the event scout YAML configuration."""

    config = yaml.safe_load(yaml_text)

    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML mapping.")

    return EventScoutConfig.model_validate(config)