from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re


@dataclass(frozen=True, slots=True)
class OpenSizeBucket:
    key: str
    minimum: float | None
    maximum: float | None


class CoreAnalyticsEngine:
    """Shared normalization and sizing rules for PokerLab analytics services."""

    POSITION_ORDER = {
        "UTG": 0,
        "UTG+1": 1,
        "HJ": 2,
        "CO": 3,
        "BTN": 4,
        "SB": 5,
        "BB": 6,
        "OTHER": 99,
    }

    BUCKET_ORDER = {
        "≤2.0x": 0,
        "2.1–2.3x": 1,
        "2.4–2.6x": 2,
        "2.7–3.0x": 3,
        "3.1x": 4,
        "3.2–3.6x": 5,
        "≥3.7x": 6,
        "UNKNOWN": 99,
    }

    POSITION_ALIASES = {
        "UTG": ("UTG", "EP", "EARLY"),
        "UTG+1": ("UTG+1", "UTG1", "EP+1"),
        "HJ": ("HJ", "HIJACK"),
        "CO": ("CO", "CUTOFF", "CUT OFF"),
        "BTN": ("BTN", "BU", "BUTTON", "DEALER"),
        "SB": ("SB", "SMALL BLIND", "SMALL_BLIND"),
        "BB": ("BB", "BIG BLIND", "BIG_BLIND"),
        "OTHER": ("OTHER",),
    }

    @classmethod
    def normalize_position(cls, value: Any) -> str:
        raw = str(value or "").strip().upper()
        if not raw:
            return "OTHER"

        for canonical, aliases in cls.POSITION_ALIASES.items():
            if raw in aliases:
                return canonical

        return raw if raw in cls.POSITION_ORDER else "OTHER"

    @classmethod
    def position_sql_values(cls, value: str) -> tuple[str, ...]:
        canonical = cls.normalize_position(value)
        return cls.POSITION_ALIASES.get(canonical, (canonical,))

    @staticmethod
    def float_or_none(value: Any) -> float | None:
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        text = str(value).strip()
        if not text:
            return None

        text = text.replace(" ", "")
        if "," in text and "." not in text:
            text = text.replace(",", ".")

        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None

        try:
            return float(match.group(0))
        except ValueError:
            return None

    @classmethod
    def parse_big_blind(cls, stakes: str) -> float | None:
        text = str(stakes or "").strip()
        if not text:
            return None

        # Handles formats such as 0.50/1, $0.5/$1, ₮0.5/₮1 and 0,50/1.
        numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
        if len(numbers) < 2:
            return None

        try:
            return float(numbers[1].replace(",", "."))
        except ValueError:
            return None

    @classmethod
    def calculate_open_size(
        cls,
        to_amount: Any,
        stakes: str,
    ) -> float | None:
        amount = cls.float_or_none(to_amount)
        big_blind = cls.parse_big_blind(stakes)

        if amount is None or big_blind is None or big_blind <= 0:
            return None

        return amount / big_blind

    @staticmethod
    def size_bucket(size_bb: float | None) -> str:
        if size_bb is None:
            return "UNKNOWN"

        # 3.1x is deliberately isolated. A small tolerance absorbs currency
        # rounding and floating-point noise around exactly 3.10.
        if size_bb <= 2.05:
            return "≤2.0x"
        if size_bb <= 2.35:
            return "2.1–2.3x"
        if size_bb <= 2.65:
            return "2.4–2.6x"
        if size_bb < 3.05:
            return "2.7–3.0x"
        if size_bb <= 3.15:
            return "3.1x"
        if size_bb < 3.65:
            return "3.2–3.6x"
        return "≥3.7x"

    @staticmethod
    def pct(numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0

        value = float(numerator) / float(denominator) * 100.0
        return max(0.0, min(100.0, value))

    @classmethod
    def diagnostic_summary(
        cls,
        rows: list[dict[str, Any]],
        requested_position: str = "",
        minimum_sample: int = 1,
    ) -> dict[str, int]:
        normalized_requested = (
            cls.normalize_position(requested_position)
            if requested_position
            else ""
        )

        position_rows = [
            row for row in rows
            if not normalized_requested
            or cls.normalize_position(row.get("position")) == normalized_requested
        ]
        valid_size = [
            row for row in position_rows
            if row.get("size_bb") is not None
        ]
        known_bucket = [
            row for row in valid_size
            if row.get("size_bucket") != "UNKNOWN"
        ]

        groups: dict[tuple[str, str], int] = {}
        for row in known_bucket:
            key = (
                cls.normalize_position(row.get("position")),
                str(row.get("size_bucket") or "UNKNOWN"),
            )
            groups[key] = groups.get(key, 0) + 1

        passing = sum(
            count for count in groups.values()
            if count >= max(1, int(minimum_sample))
        )

        return {
            "loaded_rows": len(rows),
            "position_rows": len(position_rows),
            "valid_size_rows": len(valid_size),
            "known_bucket_rows": len(known_bucket),
            "minimum_sample_pass_rows": passing,
            "groups_before_minimum": len(groups),
            "groups_after_minimum": sum(
                1 for count in groups.values()
                if count >= max(1, int(minimum_sample))
            ),
        }
