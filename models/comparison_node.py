"""Canonical strategic node definition for Unified Node Comparison."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping

from services.poker_statistics import DECISION_ACTIONS


class Position(str, Enum):
    EP = "EP"
    MP = "MP"
    MP1 = "MP1"
    CO = "CO"
    BTN = "BTN"
    SB = "SB"
    BB = "BB"
    UNKNOWN = "UNKNOWN"


class Street(str, Enum):
    PREFLOP = "PREFLOP"
    FLOP = "FLOP"
    TURN = "TURN"
    RIVER = "RIVER"


class PreflopPotType(str, Enum):
    LIMPED = "LIMPED"
    SRP = "SRP"
    THREE_BET = "THREE_BET"
    FOUR_BET_PLUS = "FOUR_BET_PLUS"
    UNKNOWN = "UNKNOWN"


class PositionRelation(str, Enum):
    IP = "IP"
    OOP = "OOP"
    UNKNOWN = "UNKNOWN"


class FacingAction(str, Enum):
    NONE = "NONE"
    CHECK = "CHECK"
    BET = "BET"
    RAISE = "RAISE"
    ALL_IN = "ALL_IN"
    UNKNOWN = "UNKNOWN"


class CohortAxis(str, Enum):
    ACTOR = "ACTOR"
    RESPONDER = "RESPONDER"
    AGGRESSOR = "AGGRESSOR"
    RELATIONSHIP = "RELATIONSHIP"


def optional_text(value: Any, *, upper: bool = True) -> str | None:
    """Trim whitespace and convert empty strings to ``None``."""
    if value is None:
        return None
    text = " ".join(str(value).strip().split())
    if not text:
        return None
    return text.upper() if upper else text


def enum_value(value: Any, enum_type: type[Enum], field_name: str) -> Enum | None:
    """Normalize a case-insensitive value into a supported enum."""
    text = optional_text(value)
    if text is None:
        return None
    aliases = {
        (Position, "MP+1"): "MP1",
        (PreflopPotType, "3BET"): "THREE_BET",
        (PreflopPotType, "4BET"): "FOUR_BET_PLUS",
        (PreflopPotType, "4BET+"): "FOUR_BET_PLUS",
        (PreflopPotType, "LIMPED"): "LIMPED",
    }
    text = aliases.get((enum_type, text), text)
    for member in enum_type:
        if text == str(member.value).upper():
            return member
    supported = ", ".join(str(member.value) for member in enum_type)
    raise ValueError(
        f"Invalid {field_name} {value!r}. Supported values: {supported}."
    )


def normalize_board(value: Any) -> str | None:
    """Normalize card spelling without introducing another board classifier."""
    text = optional_text(value, upper=False)
    if text is None:
        return None
    cards = re.findall(r"([2-9TJQKA])([SHDC])", text, re.IGNORECASE)
    compact_input = re.sub(r"[\s,\[\]-]", "", text)
    if cards and len(compact_input) == len(cards) * 2:
        return " ".join(f"{rank.upper()}{suit.lower()}" for rank, suit in cards)
    return optional_text(text)


@dataclass(frozen=True, slots=True)
class ComparisonNode:
    """Immutable, normalized definition of one strategic poker decision node."""

    site: str | None = None
    stake: str | None = None
    game_format: str | None = None
    table_size: int | None = None
    ante: float | None = None
    effective_stack_bucket: str | None = None
    hero_position: Position | str | None = None
    villain_position: Position | str | None = None
    actor_position: Position | str | None = None
    opponent_position: Position | str | None = None
    position_relation: PositionRelation | str | None = None
    preflop_pot_type: PreflopPotType | str | None = None
    preflop_action_line: str | None = None
    street: Street | str | None = None
    board: str | None = None
    board_key: str | None = None
    board_family: str | None = None
    players_remaining: int | None = None
    is_heads_up: bool | None = None
    previous_street_line: str | None = None
    facing_action: FacingAction | str | None = None
    facing_size_bucket: str | None = None
    pot_bucket: str | None = None
    spr_bucket: str | None = None
    decision_player_role: str | None = None
    legal_actions: tuple[str, ...] = ()
    cohort_axis: CohortAxis | str | None = None

    KEY_VERSION = 1

    def __post_init__(self) -> None:
        for name in (
            "site", "stake", "game_format", "effective_stack_bucket",
            "board_family", "preflop_action_line", "previous_street_line",
            "facing_size_bucket", "pot_bucket", "spr_bucket",
            "decision_player_role",
        ):
            object.__setattr__(self, name, optional_text(getattr(self, name)))
        board = normalize_board(self.board)
        object.__setattr__(self, "board", board)
        object.__setattr__(
            self, "board_key", normalize_board(self.board_key) or board
        )
        for name, enum_type in (
            ("hero_position", Position),
            ("villain_position", Position),
            ("actor_position", Position),
            ("opponent_position", Position),
            ("position_relation", PositionRelation),
            ("preflop_pot_type", PreflopPotType),
            ("street", Street),
            ("facing_action", FacingAction),
            ("cohort_axis", CohortAxis),
        ):
            object.__setattr__(
                self, name, enum_value(getattr(self, name), enum_type, name)
            )
        legal = tuple(
            sorted(
                {
                    str(action).strip().upper()
                    for action in self.legal_actions
                    if str(action).strip()
                }
            )
        )
        invalid = sorted(set(legal) - set(DECISION_ACTIONS))
        if invalid:
            raise ValueError(f"Invalid legal_actions: {', '.join(invalid)}.")
        object.__setattr__(self, "legal_actions", legal)
        if self.table_size is not None:
            size = int(self.table_size)
            if size < 2:
                raise ValueError("table_size must be at least 2.")
            object.__setattr__(self, "table_size", size)
        if self.ante is not None:
            ante = float(self.ante)
            if ante < 0:
                raise ValueError("ante cannot be negative.")
            object.__setattr__(self, "ante", ante)
        if self.players_remaining is not None:
            remaining = int(self.players_remaining)
            if remaining < 2:
                raise ValueError("players_remaining must be at least 2.")
            object.__setattr__(self, "players_remaining", remaining)
            if self.is_heads_up is not None and bool(self.is_heads_up) != (remaining == 2):
                raise ValueError("is_heads_up conflicts with players_remaining.")
        if self.is_heads_up is not None:
            object.__setattr__(self, "is_heads_up", bool(self.is_heads_up))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible representation."""
        result: dict[str, Any] = {}
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if isinstance(value, Enum):
                value = value.value
            elif isinstance(value, tuple):
                value = list(value)
            result[name] = value
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ComparisonNode:
        """Deserialize with full validation; unknown fields are rejected."""
        return cls(**dict(data))

    def to_key(self) -> str:
        """Return a process-stable, versioned SHA-256 node key."""
        canonical_json = json.dumps(
            self.to_key_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
        return f"node-v{self.KEY_VERSION}:{digest}"

    def to_key_payload(self) -> dict[str, Any]:
        """Return the sole canonical payload used for node identity hashing."""
        return self.to_dict()
