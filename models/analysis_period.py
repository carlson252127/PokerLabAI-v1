"""Time period model kept separate from strategic node identity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone as fixed_timezone
from enum import Enum
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class BucketType(str, Enum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    CUSTOM = "CUSTOM"


def _zone(timezone: str):
    try:
        return ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        if timezone == "Europe/Istanbul":
            return fixed_timezone(timedelta(hours=3), name="Europe/Istanbul")
        raise


def _datetime(value: datetime | date | str, timezone: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, date):
        result = datetime.combine(value, time.min)
    else:
        result = datetime.fromisoformat(str(value).strip())
    zone = _zone(timezone)
    if result.tzinfo is None:
        result = result.replace(tzinfo=zone)
    return result


@dataclass(frozen=True, slots=True)
class AnalysisPeriod:
    """A timezone-explicit half-open interval ``[date_from, date_to)``."""

    date_from: datetime | date | str
    date_to: datetime | date | str
    timezone: str = "Europe/Istanbul"
    label: str | None = field(default=None, compare=False, hash=False)
    bucket_type: BucketType | str = BucketType.CUSTOM

    def __post_init__(self) -> None:
        timezone = str(self.timezone or "").strip()
        if not timezone:
            raise ValueError("timezone cannot be empty.")
        try:
            _zone(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone {timezone!r}.") from exc
        object.__setattr__(self, "timezone", timezone)
        start = _datetime(self.date_from, timezone)
        end = _datetime(self.date_to, timezone)
        if start >= end:
            raise ValueError("date_from must be earlier than date_to.")
        object.__setattr__(self, "date_from", start)
        object.__setattr__(self, "date_to", end)
        label = " ".join(str(self.label or "").strip().split()) or None
        object.__setattr__(self, "label", label)
        try:
            bucket = (
                self.bucket_type
                if isinstance(self.bucket_type, BucketType)
                else BucketType(str(self.bucket_type).strip().upper())
            )
        except ValueError as exc:
            raise ValueError(f"Invalid bucket_type {self.bucket_type!r}.") from exc
        object.__setattr__(self, "bucket_type", bucket)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "timezone": self.timezone,
            "label": self.label,
            "bucket_type": self.bucket_type.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AnalysisPeriod:
        return cls(**dict(data))
