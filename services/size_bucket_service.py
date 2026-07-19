from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True, slots=True)
class SizeBucket:
    key: str
    label: str
    minimum: float
    maximum: Optional[float]
    color: str

POSTFLOP_BUCKETS = (
    SizeBucket("MICRO", "Micro 0–20%", 0.0, 20.0, "#64748b"),
    SizeBucket("SMALL", "Small 21–30%", 20.0, 30.0, "#3b82f6"),
    SizeBucket("SMALL_PLUS", "Small+ 31–40%", 30.0, 40.0, "#2563eb"),
    SizeBucket("HALF", "Half Pot 41–50%", 40.0, 50.0, "#22c55e"),
    SizeBucket("MEDIUM", "Medium 51–60%", 50.0, 60.0, "#16a34a"),
    SizeBucket("MEDIUM_PLUS", "Medium+ 61–75%", 60.0, 75.0, "#eab308"),
    SizeBucket("LARGE", "Large 76–90%", 75.0, 90.0, "#f59e0b"),
    SizeBucket("POT", "Pot 91–110%", 90.0, 110.0, "#f97316"),
    SizeBucket("OVERBET", "Overbet 111–140%", 110.0, 140.0, "#ef4444"),
    SizeBucket("BIG_OVERBET", "Big Overbet 141–175%", 140.0, 175.0, "#dc2626"),
    SizeBucket("HUGE_OVERBET", "Huge Overbet 176–225%", 175.0, 225.0, "#a855f7"),
    SizeBucket("EXTREME", "Extreme 226%+", 225.0, None, "#7e22ce"),
)

OPEN_BUCKETS = (
    SizeBucket("OPEN_2_0", "2.0x", 0.0, 2.05, "#3b82f6"),
    SizeBucket("OPEN_2_25", "2.1–2.25x", 2.05, 2.25, "#2563eb"),
    SizeBucket("OPEN_2_5", "2.26–2.5x", 2.25, 2.50, "#22c55e"),
    SizeBucket("OPEN_2_75", "2.51–2.75x", 2.50, 2.75, "#16a34a"),
    SizeBucket("OPEN_3_0", "2.76–3.0x", 2.75, 3.00, "#eab308"),
    SizeBucket("OPEN_3_5", "3.01–3.5x", 3.00, 3.50, "#f59e0b"),
    SizeBucket("OPEN_4_0", "3.51–4.0x", 3.50, 4.00, "#ef4444"),
    SizeBucket("OPEN_4_PLUS", "4.01x+", 4.00, None, "#a855f7"),
)

def _find(value: float, buckets: tuple[SizeBucket, ...]) -> SizeBucket:
    number = float(value)
    for bucket in buckets:
        if number > bucket.minimum and (bucket.maximum is None or number <= bucket.maximum):
            return bucket
    return buckets[0]

def postflop_bucket(percent: float, all_in: bool = False) -> str:
    if all_in:
        return "All-in"
    return _find(percent, POSTFLOP_BUCKETS).label

def open_bucket(size_bb: float) -> str:
    return _find(size_bb, OPEN_BUCKETS).label

def color_for_size(value: float, preflop: bool = False) -> str:
    return _find(value, OPEN_BUCKETS if preflop else POSTFLOP_BUCKETS).color
