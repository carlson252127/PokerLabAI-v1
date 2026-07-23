"""Validated comparison, cohort, GTO, and sample result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
from typing import Any, Mapping

from models.analysis_period import AnalysisPeriod
from models.comparison_node import optional_text
from models.node_identity import NodeIdentity
from services.poker_statistics import DECISION_ACTIONS


def _count(value: Any, name: str) -> int:
    result = int(value)
    if result < 0:
        raise ValueError(f"{name} cannot be negative.")
    return result


def _ratio(value: Any, name: str, *, optional: bool = False) -> float | None:
    if value is None and optional:
        return None
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError(f"{name} must be between 0 and 1.")
    return result


def _warnings(values: Any) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            text
            for value in (values or ())
            if (text := optional_text(value, upper=False)) is not None
        )
    )


def _datetime(value: datetime | str, name: str) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware.")
    return result


class CohortType(str, Enum):
    HUMAN_POOL = "HUMAN_POOL"
    BOT_GROUP = "BOT_GROUP"
    PLAYER = "PLAYER"
    ALIAS = "ALIAS"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True, slots=True)
class CohortReference:
    """Versioned, namespaced cohort snapshot reference."""

    cohort_type: CohortType | str
    cohort_id: str
    cohort_version: int
    snapshot_at: datetime | str
    display_name: str | None = field(default=None, compare=False, hash=False)

    def __post_init__(self) -> None:
        try:
            kind = (
                self.cohort_type
                if isinstance(self.cohort_type, CohortType)
                else CohortType(str(self.cohort_type).strip().upper())
            )
        except ValueError as exc:
            raise ValueError(f"Invalid cohort_type {self.cohort_type!r}.") from exc
        object.__setattr__(self, "cohort_type", kind)
        cohort_id = optional_text(self.cohort_id, upper=False)
        if cohort_id is None or ":" not in cohort_id:
            raise ValueError("cohort_id must use an explicit namespace, e.g. site:id.")
        object.__setattr__(self, "cohort_id", cohort_id)
        version = int(self.cohort_version)
        if version < 1:
            raise ValueError("cohort_version must be at least 1.")
        object.__setattr__(self, "cohort_version", version)
        object.__setattr__(
            self, "snapshot_at", _datetime(self.snapshot_at, "snapshot_at")
        )
        object.__setattr__(
            self, "display_name", optional_text(self.display_name, upper=False)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort_type": self.cohort_type.value,
            "cohort_id": self.cohort_id,
            "cohort_version": self.cohort_version,
            "snapshot_at": self.snapshot_at.isoformat(),
            "display_name": self.display_name,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CohortReference:
        return cls(**dict(data))


@dataclass(frozen=True, slots=True)
class ActionFrequency:
    """An action frequency derived exclusively from safe integer counters."""

    action: str
    opportunities: int
    action_count: int
    sample_hands: int = 0
    sample_players: int = 0
    frequency: float | None = field(init=False)

    def __post_init__(self) -> None:
        action = str(self.action or "").strip().upper()
        if action not in DECISION_ACTIONS:
            raise ValueError(f"Invalid action {self.action!r}.")
        object.__setattr__(self, "action", action)
        for name in ("opportunities", "action_count", "sample_hands", "sample_players"):
            object.__setattr__(self, name, _count(getattr(self, name), name))
        if self.action_count > self.opportunities:
            raise ValueError("action_count cannot exceed opportunities.")
        object.__setattr__(
            self,
            "frequency",
            self.action_count / self.opportunities if self.opportunities else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "opportunities": self.opportunities,
            "action_count": self.action_count,
            "frequency": self.frequency,
            "sample_hands": self.sample_hands,
            "sample_players": self.sample_players,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ActionFrequency:
        values = dict(data)
        values.pop("frequency", None)
        return cls(**values)


@dataclass(frozen=True, slots=True)
class SampleQuality:
    """Precomputed sample reliability and player-concentration metrics."""

    confidence_score: float
    largest_player_share: float
    top_five_player_share: float
    sample_hands: int
    sample_players: int
    opportunities: int
    is_low_sample: bool
    is_player_dominated: bool
    model_version: str
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("confidence_score", "largest_player_share", "top_five_player_share"):
            object.__setattr__(self, name, _ratio(getattr(self, name), name))
        if self.largest_player_share > self.top_five_player_share:
            raise ValueError("largest_player_share cannot exceed top_five_player_share.")
        for name in ("sample_hands", "sample_players", "opportunities"):
            object.__setattr__(self, name, _count(getattr(self, name), name))
        version = optional_text(self.model_version, upper=False)
        if version is None:
            raise ValueError("model_version cannot be empty.")
        object.__setattr__(self, "model_version", version)
        object.__setattr__(self, "is_low_sample", bool(self.is_low_sample))
        object.__setattr__(self, "is_player_dominated", bool(self.is_player_dominated))
        object.__setattr__(self, "warnings", _warnings(self.warnings))

    def to_dict(self) -> dict[str, Any]:
        return {
            name: list(value) if isinstance(value, tuple) else value
            for name in self.__dataclass_fields__
            if (value := getattr(self, name)) is not None
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SampleQuality:
        return cls(**dict(data))


class GTOResolutionType(str, Enum):
    EXACT = "EXACT"
    BUCKET_FALLBACK = "BUCKET_FALLBACK"
    SIMILAR_BOARD_FALLBACK = "SIMILAR_BOARD_FALLBACK"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class GTOReferenceStats:
    """Versioned solver reference with an explicit resolution state."""

    actions: tuple[ActionFrequency, ...] = ()
    solver_name: str | None = None
    solver_version: str | None = None
    tree_id: str | None = None
    effective_stack: str | None = None
    rake_profile: str | None = None
    source: str | None = None
    resolution_type: GTOResolutionType | str = GTOResolutionType.UNAVAILABLE
    match_quality: float | None = None
    reference_id: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        resolution = (
            self.resolution_type
            if isinstance(self.resolution_type, GTOResolutionType)
            else GTOResolutionType(str(self.resolution_type).strip().upper())
        )
        object.__setattr__(self, "resolution_type", resolution)
        object.__setattr__(self, "actions", tuple(self.actions))
        if resolution == GTOResolutionType.UNAVAILABLE:
            if self.actions:
                raise ValueError("UNAVAILABLE GTO reference cannot contain actions.")
            if self.match_quality is not None:
                raise ValueError("UNAVAILABLE GTO match_quality must be None.")
        elif not self.actions:
            raise ValueError("Available GTO reference must contain actions.")
        if self.match_quality is not None:
            object.__setattr__(
                self, "match_quality", _ratio(self.match_quality, "match_quality")
            )
        for name in (
            "solver_name", "solver_version", "tree_id", "effective_stack",
            "rake_profile", "source", "reference_id",
        ):
            object.__setattr__(self, name, optional_text(getattr(self, name), upper=False))
        warnings = list(_warnings(self.warnings))
        frequencies = [item.frequency for item in self.actions if item.frequency is not None]
        if frequencies and abs(sum(frequencies) - 1.0) > 0.02:
            warnings.append(
                "Action frequencies do not sum to 1; split sizes may be incomplete."
            )
        object.__setattr__(self, "warnings", _warnings(warnings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [item.to_dict() for item in self.actions],
            "solver_name": self.solver_name,
            "solver_version": self.solver_version,
            "tree_id": self.tree_id,
            "effective_stack": self.effective_stack,
            "rake_profile": self.rake_profile,
            "source": self.source,
            "resolution_type": self.resolution_type.value,
            "match_quality": self.match_quality,
            "reference_id": self.reference_id,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GTOReferenceStats:
        values = dict(data)
        values["actions"] = tuple(
            ActionFrequency.from_dict(item) for item in values.get("actions", ())
        )
        return cls(**values)


@dataclass(frozen=True, slots=True)
class GroupNodeStats:
    group_name: str
    cohort: CohortReference
    actions: tuple[ActionFrequency, ...]
    sample_hands: int
    sample_players: int
    opportunities: int
    data_from: datetime | str
    data_to: datetime | str
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        name = optional_text(self.group_name, upper=False)
        if name is None:
            raise ValueError("group_name cannot be empty.")
        object.__setattr__(self, "group_name", name)
        if not isinstance(self.cohort, CohortReference):
            raise TypeError("cohort must be a CohortReference.")
        object.__setattr__(self, "actions", tuple(self.actions))
        for field_name in ("sample_hands", "sample_players", "opportunities"):
            object.__setattr__(self, field_name, _count(getattr(self, field_name), field_name))
        start = _datetime(self.data_from, "data_from")
        end = _datetime(self.data_to, "data_to")
        if start >= end:
            raise ValueError("data_from must be earlier than data_to.")
        object.__setattr__(self, "data_from", start)
        object.__setattr__(self, "data_to", end)
        object.__setattr__(self, "warnings", _warnings(self.warnings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_name": self.group_name,
            "cohort": self.cohort.to_dict(),
            "actions": [item.to_dict() for item in self.actions],
            "sample_hands": self.sample_hands,
            "sample_players": self.sample_players,
            "opportunities": self.opportunities,
            "data_from": self.data_from.isoformat(),
            "data_to": self.data_to.isoformat(),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> GroupNodeStats:
        values = dict(data)
        values["cohort"] = CohortReference.from_dict(values["cohort"])
        values["actions"] = tuple(
            ActionFrequency.from_dict(item) for item in values.get("actions", ())
        )
        return cls(**values)


@dataclass(frozen=True, slots=True)
class ActionDeviation:
    action: str
    observed_frequency: float
    reference_frequency: float | None
    percentage_point_difference: float | None = field(init=False)
    relative_difference: float | None = field(init=False)

    def __post_init__(self) -> None:
        action = str(self.action or "").strip().upper()
        if action not in DECISION_ACTIONS:
            raise ValueError(f"Invalid action {self.action!r}.")
        object.__setattr__(self, "action", action)
        observed = _ratio(self.observed_frequency, "observed_frequency")
        reference = _ratio(
            self.reference_frequency, "reference_frequency", optional=True
        )
        object.__setattr__(self, "observed_frequency", observed)
        object.__setattr__(self, "reference_frequency", reference)
        pp = None if reference is None else (observed - reference) * 100.0
        relative = (
            None if reference in (None, 0) else (observed - reference) / reference
        )
        object.__setattr__(self, "percentage_point_difference", pp)
        object.__setattr__(self, "relative_difference", relative)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "observed_frequency": self.observed_frequency,
            "reference_frequency": self.reference_frequency,
            "percentage_point_difference": self.percentage_point_difference,
            "relative_difference": self.relative_difference,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ActionDeviation:
        values = dict(data)
        values.pop("percentage_point_difference", None)
        values.pop("relative_difference", None)
        return cls(**values)


@dataclass(frozen=True, slots=True)
class NodeComparisonResult:
    """Complete nested result; pool data is required, bot and GTO are optional."""

    node_identity: NodeIdentity
    period: AnalysisPeriod
    pool_stats: GroupNodeStats
    bot_stats: GroupNodeStats | None = None
    gto_stats: GTOReferenceStats | None = None
    pool_vs_gto: tuple[ActionDeviation, ...] = ()
    bots_vs_gto: tuple[ActionDeviation, ...] = ()
    bots_vs_pool: tuple[ActionDeviation, ...] = ()
    pool_sample_quality: SampleQuality | None = None
    bot_sample_quality: SampleQuality | None = None
    exploit_recommendations: tuple[Any, ...] = ()
    query_duration_ms: float = 0.0
    calculated_at: datetime | str = ""
    source_generation: str = "UNKNOWN"
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.node_identity, NodeIdentity):
            raise TypeError("node_identity must be a NodeIdentity.")
        if not isinstance(self.period, AnalysisPeriod):
            raise TypeError("period must be an AnalysisPeriod.")
        if not isinstance(self.pool_stats, GroupNodeStats):
            raise ValueError("pool_stats is required.")
        for name in ("pool_vs_gto", "bots_vs_gto", "bots_vs_pool", "exploit_recommendations"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        duration = float(self.query_duration_ms)
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("query_duration_ms cannot be negative.")
        object.__setattr__(self, "query_duration_ms", duration)
        object.__setattr__(
            self, "calculated_at", _datetime(self.calculated_at, "calculated_at")
        )
        generation = optional_text(self.source_generation, upper=False)
        if generation is None:
            raise ValueError("source_generation cannot be empty.")
        object.__setattr__(self, "source_generation", generation)
        object.__setattr__(self, "warnings", _warnings(self.warnings))

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_identity": self.node_identity.to_dict(),
            "period": self.period.to_dict(),
            "pool_stats": self.pool_stats.to_dict(),
            "bot_stats": self.bot_stats.to_dict() if self.bot_stats else None,
            "gto_stats": self.gto_stats.to_dict() if self.gto_stats else None,
            "pool_vs_gto": [item.to_dict() for item in self.pool_vs_gto],
            "bots_vs_gto": [item.to_dict() for item in self.bots_vs_gto],
            "bots_vs_pool": [item.to_dict() for item in self.bots_vs_pool],
            "pool_sample_quality": (
                self.pool_sample_quality.to_dict() if self.pool_sample_quality else None
            ),
            "bot_sample_quality": (
                self.bot_sample_quality.to_dict() if self.bot_sample_quality else None
            ),
            "exploit_recommendations": [
                item.to_dict() for item in self.exploit_recommendations
            ],
            "query_duration_ms": self.query_duration_ms,
            "calculated_at": self.calculated_at.isoformat(),
            "source_generation": self.source_generation,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NodeComparisonResult:
        from models.exploit_models import ExploitRecommendation

        values = dict(data)
        values["node_identity"] = NodeIdentity.from_dict(values["node_identity"])
        values["period"] = AnalysisPeriod.from_dict(values["period"])
        values["pool_stats"] = GroupNodeStats.from_dict(values["pool_stats"])
        values["bot_stats"] = (
            GroupNodeStats.from_dict(values["bot_stats"])
            if values.get("bot_stats") is not None else None
        )
        values["gto_stats"] = (
            GTOReferenceStats.from_dict(values["gto_stats"])
            if values.get("gto_stats") is not None else None
        )
        for name in ("pool_vs_gto", "bots_vs_gto", "bots_vs_pool"):
            values[name] = tuple(
                ActionDeviation.from_dict(item) for item in values.get(name, ())
            )
        for name in ("pool_sample_quality", "bot_sample_quality"):
            values[name] = (
                SampleQuality.from_dict(values[name])
                if values.get(name) is not None else None
            )
        values["exploit_recommendations"] = tuple(
            ExploitRecommendation.from_dict(item)
            for item in values.get("exploit_recommendations", ())
        )
        return cls(**values)
