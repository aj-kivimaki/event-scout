from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from src.event_digest.dates import max_lookahead_weeks


class CenterConfig(BaseModel):
    # Same geographic contract as the radius-filter API parameters.
    model_config = ConfigDict(allow_inf_nan=False)

    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class EventScoutConfig(BaseModel):
    # Reject NaN/inf floats (radius_km); gt=0 alone accepts infinity.
    # Model config is not inherited by the nested CenterConfig, which sets
    # its own.
    model_config = ConfigDict(allow_inf_nan=False)

    center: CenterConfig
    radius_km: float = Field(gt=0)
    lookahead_weeks: int = Field(gt=0)
    categories: list[str] = Field(min_length=1)

    @field_validator("lookahead_weeks")
    @classmethod
    def lookahead_weeks_fits_date_range(cls, value: int) -> int:
        """Reject lookaheads whose date range cannot be represented."""

        max_weeks = max_lookahead_weeks()

        if value > max_weeks:
            # Same error as Pydantic's built-in le constraint.
            raise PydanticCustomError(
                "less_than_equal",
                "Input should be less than or equal to {le}",
                {"le": max_weeks},
            )

        return value
