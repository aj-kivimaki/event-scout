from pydantic import BaseModel, Field


class CenterConfig(BaseModel):
    name: str
    latitude: float
    longitude: float


class EventScoutConfig(BaseModel):
    center: CenterConfig
    radius_km: float = Field(gt=0)
    lookahead_weeks: int = Field(gt=0)
    categories: list[str] = Field(min_length=1)