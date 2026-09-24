import math
import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import get_settings
from app.models import AlertStatus, Operator

METRIC_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class DeviceCreated(BaseModel):
    id: uuid.UUID
    name: str
    api_key: str = Field(description="Shown once. Store it on the device.")


class ReadingIn(BaseModel):
    metric: str = Field(pattern=METRIC_PATTERN, examples=["temperature_c"])
    value: float
    ts: datetime

    @field_validator("value")
    @classmethod
    def value_is_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("value must be a finite number")
        return v

    @field_validator("ts")
    @classmethod
    def ts_is_aware_and_not_future(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("ts must include a timezone, e.g. 2026-09-28T12:00:00Z")
        skew = timedelta(seconds=get_settings().max_future_skew_seconds)
        if v > datetime.now(UTC) + skew:
            raise ValueError("ts is too far in the future")
        return v.astimezone(UTC)


class ReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metric: str
    value: float
    ts: datetime


MAX_BATCH_SIZE = 1000


class ReadingBatchIn(BaseModel):
    readings: list[ReadingIn] = Field(min_length=1, max_length=MAX_BATCH_SIZE)


class ReadingBatchResult(BaseModel):
    received: int
    inserted: int
    duplicates: int


class AlertRuleIn(BaseModel):
    metric: str = Field(pattern=METRIC_PATTERN)
    operator: Operator
    threshold: float

    @field_validator("threshold")
    @classmethod
    def threshold_is_finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("threshold must be a finite number")
        return v


class AlertRuleOut(AlertRuleIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: int
    device_id: uuid.UUID
    status: AlertStatus
    trigger_value: float
    opened_at: datetime
    resolved_at: datetime | None
