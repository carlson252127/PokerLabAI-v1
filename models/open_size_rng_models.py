from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class OpenSizeRngReport:
    classification: str
    used_records: int
    duplicate_records: int
    excluded_records: int
    player_shares: list[dict[str, Any]] = field(default_factory=list)
    position_distribution: list[dict[str, Any]] = field(default_factory=list)
    condition_effects: list[dict[str, Any]] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    model_metrics: list[dict[str, Any]] = field(default_factory=list)
    serial_metrics: dict[str, Any] = field(default_factory=dict)
    session_stability: dict[str, Any] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    natural_high_size_rate: float | None = None
    equal_player_high_size_rate: float | None = None
    high_size_ci_low: float | None = None
    high_size_ci_high: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

