from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import math
from typing import Any, Mapping

from models.comparison_node import Street


class DecisionType(str, Enum):
    CHECK_OR_BET = "CHECK_OR_BET"
    CHECK_OR_RAISE = "CHECK_OR_RAISE"
    FOLD_CALL_RAISE = "FOLD_CALL_RAISE"
    FOLD_CALL_OR_RAISE = "FOLD_CALL_RAISE"
    CALL_OR_RAISE = "CALL_OR_RAISE"
    CHECK_CALL_RAISE = "CHECK_CALL_RAISE"
    FOLD_OR_CONTINUE = "FOLD_OR_CONTINUE"


def _required_text(value: Any, field_name: str) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        raise ValueError(f"{field_name} cannot be empty.")
    return text


def _optional_number(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite.")
    if number < 0:
        raise ValueError(f"{field_name} cannot be negative.")
    return number


@dataclass(frozen=True, slots=True)
class DecisionOpportunity:
    hand_id: str
    player_id: str
    street: Street | str
    decision_index: int
    node_key: str
    decision_type: DecisionType | str
    facing_action: str
    available_actions: tuple[str, ...]
    chosen_action: str
    amount: float | None = None
    raise_to: float | None = None
    pot_before_action: float | None = None
    size_ratio: float | None = None
    is_valid: bool = True
    is_multiway: bool = False
    warning: str | None = None
    site: str | None = None
    opponent: str | None = None
    facing_amount: float | None = None
    effective_stack: float | None = None
    position: str | None = None
    opponent_position: str | None = None
    is_in_position: bool | None = None
    is_heads_up: bool | None = None
    players_remaining: int | None = None
    action_index: int | None = None
    timestamp: datetime | str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "hand_id", _required_text(self.hand_id, "hand_id")
        )
        object.__setattr__(
            self, "player_id", _required_text(self.player_id, "player_id")
        )
        object.__setattr__(self, "node_key", str(self.node_key or "").strip())

        try:
            street = (
                self.street
                if isinstance(self.street, Street)
                else Street(str(self.street).strip().upper())
            )
        except ValueError as exc:
            raise ValueError(f"Invalid street {self.street!r}.") from exc
        object.__setattr__(self, "street", street)

        try:
            decision_type_text = str(self.decision_type).strip().upper()
            if decision_type_text == "FOLD_CALL_OR_RAISE":
                decision_type_text = "FOLD_CALL_RAISE"
            decision_type = (
                self.decision_type
                if isinstance(self.decision_type, DecisionType)
                else DecisionType(decision_type_text)
            )
        except ValueError as exc:
            raise ValueError(
                f"Invalid decision_type {self.decision_type!r}."
            ) from exc
        object.__setattr__(self, "decision_type", decision_type)

        decision_index = int(self.decision_index)
        if decision_index < 0:
            raise ValueError("decision_index cannot be negative.")
        object.__setattr__(self, "decision_index", decision_index)

        facing_action = str(self.facing_action or "NONE").strip().upper()
        chosen_action = _required_text(
            self.chosen_action, "chosen_action"
        ).upper()
        action_order = {"CHECK": 0, "BET": 1, "FOLD": 2, "CALL": 3, "RAISE": 4}
        available_set = {
            _required_text(action, "available_action").upper()
            for action in self.available_actions
        }
        unknown_actions = sorted(set(available_set) - set(action_order))
        if unknown_actions:
            raise ValueError(
                f"Invalid available_actions: {', '.join(unknown_actions)}."
            )
        available = tuple(
            sorted(available_set, key=action_order.__getitem__)
        )
        expected_actions = {
            DecisionType.CHECK_OR_BET: {"CHECK", "BET"},
            DecisionType.CHECK_OR_RAISE: {"CHECK", "RAISE"},
            DecisionType.FOLD_CALL_RAISE: {"FOLD", "CALL", "RAISE"},
            DecisionType.CALL_OR_RAISE: {"CALL", "RAISE"},
            DecisionType.CHECK_CALL_RAISE: {"CHECK", "CALL", "RAISE"},
            DecisionType.FOLD_OR_CONTINUE: {"FOLD", "CALL", "RAISE"},
        }[decision_type]
        if available_set != expected_actions:
            expected = ", ".join(
                sorted(expected_actions, key=action_order.__getitem__)
            )
            raise ValueError(
                f"{decision_type.value} requires available_actions "
                f"({expected})."
            )
        if chosen_action not in available:
            raise ValueError(
                "chosen_action must be present in available_actions."
            )
        object.__setattr__(self, "facing_action", facing_action)
        object.__setattr__(self, "chosen_action", chosen_action)
        object.__setattr__(self, "available_actions", available)

        amount = _optional_number(self.amount, "amount")
        raise_to = _optional_number(self.raise_to, "raise_to")
        pot = _optional_number(
            self.pot_before_action, "pot_before_action"
        )
        object.__setattr__(self, "amount", amount)
        object.__setattr__(self, "raise_to", raise_to)
        object.__setattr__(self, "pot_before_action", pot)
        object.__setattr__(
            self,
            "facing_amount",
            _optional_number(self.facing_amount, "facing_amount"),
        )
        object.__setattr__(
            self,
            "effective_stack",
            _optional_number(self.effective_stack, "effective_stack"),
        )

        ratio = amount / pot if amount is not None and pot not in (None, 0) else None
        object.__setattr__(self, "size_ratio", ratio)
        object.__setattr__(self, "is_valid", bool(self.is_valid))
        object.__setattr__(self, "is_multiway", bool(self.is_multiway))
        object.__setattr__(
            self,
            "site",
            " ".join(str(self.site or "").strip().split()) or None,
        )
        object.__setattr__(
            self,
            "opponent",
            " ".join(str(self.opponent or "").strip().split()) or None,
        )
        for name in ("position", "opponent_position"):
            value = " ".join(
                str(getattr(self, name) or "").strip().split()
            ).upper()
            object.__setattr__(self, name, value or None)
        for name in ("is_in_position", "is_heads_up"):
            value = getattr(self, name)
            object.__setattr__(
                self, name, None if value is None else bool(value)
            )
        if self.players_remaining is not None:
            players_remaining = int(self.players_remaining)
            if players_remaining < 1:
                raise ValueError("players_remaining must be positive.")
            object.__setattr__(
                self, "players_remaining", players_remaining
            )
        action_index = (
            self.decision_index
            if self.action_index is None
            else int(self.action_index)
        )
        if action_index < 0:
            raise ValueError("action_index cannot be negative.")
        object.__setattr__(self, "action_index", action_index)
        if self.timestamp is not None and not isinstance(
            self.timestamp, datetime
        ):
            object.__setattr__(
                self,
                "timestamp",
                datetime.fromisoformat(str(self.timestamp)),
            )
        warning = " ".join(str(self.warning or "").strip().split()) or None
        object.__setattr__(self, "warning", warning)

    @property
    def identity(self) -> tuple[str, str, str, int]:
        return (
            self.hand_id,
            self.player_id.casefold(),
            self.street.value,
            self.decision_index,
        )

    def to_key(self) -> str:
        payload = json.dumps(
            self.identity,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"decision:v1:sha256:{digest}"

    @property
    def actor(self) -> str:
        """Return the canonical acting player identifier."""
        return self.player_id

    @property
    def legal_actions(self) -> tuple[str, ...]:
        """Return the canonical legal-action tuple."""
        return self.available_actions

    def to_dict(self) -> dict[str, Any]:
        return {
            "hand_id": self.hand_id,
            "player_id": self.player_id,
            "street": self.street.value,
            "decision_index": self.decision_index,
            "node_key": self.node_key,
            "decision_type": self.decision_type.value,
            "facing_action": self.facing_action,
            "available_actions": list(self.available_actions),
            "chosen_action": self.chosen_action,
            "amount": self.amount,
            "raise_to": self.raise_to,
            "pot_before_action": self.pot_before_action,
            "size_ratio": self.size_ratio,
            "is_valid": self.is_valid,
            "is_multiway": self.is_multiway,
            "warning": self.warning,
            "site": self.site,
            "opponent": self.opponent,
            "facing_amount": self.facing_amount,
            "effective_stack": self.effective_stack,
            "position": self.position,
            "opponent_position": self.opponent_position,
            "is_in_position": self.is_in_position,
            "is_heads_up": self.is_heads_up,
            "players_remaining": self.players_remaining,
            "action_index": self.action_index,
            "timestamp": (
                self.timestamp.isoformat()
                if isinstance(self.timestamp, datetime)
                else self.timestamp
            ),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> DecisionOpportunity:
        values = dict(data)
        values.pop("size_ratio", None)
        values["available_actions"] = tuple(
            values.get("available_actions", ())
        )
        return cls(**values)
