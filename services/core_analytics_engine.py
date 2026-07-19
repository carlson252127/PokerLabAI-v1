from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
import math
import re


@dataclass(frozen=True, slots=True)
class OpenSizeBucket:
    key: str
    minimum: float | None
    maximum: float | None


class CoreAnalyticsEngine:
    """Shared normalization, scoring and sizing rules for PokerLab analytics."""

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
            result = float(value)
            return result if math.isfinite(result) else None

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
            result = float(match.group(0))
            return result if math.isfinite(result) else None
        except ValueError:
            return None

    @classmethod
    def parse_big_blind(cls, stakes: str) -> float | None:
        text = str(stakes or "").strip()
        if not text:
            return None

        numbers = re.findall(r"\d+(?:[.,]\d+)?", text)
        if len(numbers) < 2:
            return None

        try:
            result = float(numbers[1].replace(",", "."))
            return result if result > 0 else None
        except ValueError:
            return None

    @classmethod
    def calculate_open_size(cls, to_amount: Any, stakes: str) -> float | None:
        amount = cls.float_or_none(to_amount)
        big_blind = cls.parse_big_blind(stakes)
        if amount is None or big_blind is None:
            return None
        return amount / big_blind

    @staticmethod
    def size_bucket(size_bb: float | None) -> str:
        if size_bb is None:
            return "UNKNOWN"
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
    def pct(numerator: int | float, denominator: int | float) -> float:
        if denominator <= 0:
            return 0.0
        value = float(numerator) / float(denominator) * 100.0
        return max(0.0, min(100.0, value))

    @staticmethod
    def safe_div(numerator: int | float, denominator: int | float) -> float:
        return float(numerator) / float(denominator) if denominator else 0.0

    @staticmethod
    def weighted_average(values: Iterable[tuple[float | None, int | float]]) -> float:
        weighted_total = 0.0
        total_weight = 0.0
        for value, weight in values:
            if value is None or weight is None:
                continue
            weight_f = float(weight)
            if weight_f <= 0:
                continue
            weighted_total += float(value) * weight_f
            total_weight += weight_f
        return weighted_total / total_weight if total_weight else 0.0

    @staticmethod
    def confidence_label(sample: int) -> str:
        sample = max(0, int(sample))
        if sample >= 5000:
            return "Çok Yüksek"
        if sample >= 1500:
            return "Yüksek"
        if sample >= 500:
            return "Orta"
        if sample >= 100:
            return "Düşük"
        return "Çok Düşük"

    @staticmethod
    def confidence_factor(sample: int) -> float:
        sample = max(0, int(sample))
        if sample == 0:
            return 0.0
        return min(1.0, math.log10(max(sample, 10)) / 4.0)

    @classmethod
    def exploit_score(
        cls,
        deviation: float,
        sample: int,
        extra_edge: float = 0.0,
    ) -> int:
        raw = abs(float(deviation)) * 2.0 + max(0.0, float(extra_edge))
        score = raw * cls.confidence_factor(sample)
        return int(round(max(0.0, min(100.0, score))))

    @staticmethod
    def deviation_label(value: float | None) -> str:
        if value is None:
            return "—"
        absolute = abs(float(value))
        if absolute < 3:
            return "Yakın"
        if absolute < 7:
            return "Orta"
        if absolute < 12:
            return "Yüksek"
        return "Çok Yüksek"

    @staticmethod
    def compact_number(value: int | float) -> str:
        number = float(value or 0)
        absolute = abs(number)
        if absolute >= 1_000_000_000:
            return f"{number / 1_000_000_000:.1f}B"
        if absolute >= 1_000_000:
            return f"{number / 1_000_000:.1f}M"
        if absolute >= 1_000:
            return f"{number / 1_000:.1f}K"
        return f"{int(number):,}".replace(",", ".")

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
        valid_size = [row for row in position_rows if row.get("size_bb") is not None]
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

        min_sample = max(1, int(minimum_sample))
        passing = sum(count for count in groups.values() if count >= min_sample)

        return {
            "loaded_rows": len(rows),
            "position_rows": len(position_rows),
            "valid_size_rows": len(valid_size),
            "known_bucket_rows": len(known_bucket),
            "minimum_sample_pass_rows": passing,
            "groups_before_minimum": len(groups),
            "groups_after_minimum": sum(
                1 for count in groups.values() if count >= min_sample
            ),
        }

    @classmethod
    def ratio_metric(
        cls,
        made: int | float,
        opportunities: int | float,
        *,
        nullable: bool = True,
    ) -> float | None:
        if not opportunities:
            return None if nullable else 0.0
        return cls.pct(made, opportunities)

    @classmethod
    def calculate_showdown_metrics(
        cls,
        *,
        saw_flop: int,
        won_postflop: int,
        went_showdown: int,
        won_showdown: int,
    ) -> dict[str, float | None]:
        """Canonical PokerLab definitions for WWSF, WTSD and W$SD."""
        return {
            "wwsf": cls.ratio_metric(won_postflop, saw_flop),
            "wtsd": cls.ratio_metric(went_showdown, saw_flop),
            "wsd": cls.ratio_metric(won_showdown, went_showdown),
        }

    @classmethod
    def calculate_action_metric(
        cls,
        made: int,
        opportunities: int,
    ) -> dict[str, int | float | None | str]:
        value = cls.ratio_metric(made, opportunities)
        return {
            "value": value,
            "made": int(made),
            "opportunities": int(opportunities),
            "confidence": cls.confidence_label(opportunities),
        }

    @classmethod
    def merge_metrics(cls, *groups: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for group in groups:
            merged.update(group)
        return merged

    @classmethod
    def minimum_positive_sample(cls, row: dict[str, Any], keys: Iterable[str]) -> int:
        samples = [int(row.get(key) or 0) for key in keys]
        positive = [sample for sample in samples if sample > 0]
        return min(positive) if positive else 0

    @classmethod
    def row_confidence(cls, row: dict[str, Any], sample_keys: Iterable[str]) -> str:
        return cls.confidence_label(cls.minimum_positive_sample(row, sample_keys))
