from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
from typing import Any, Mapping

from models.comparison_node import Street


class DecisionType(str, Enum):
    CHECK_OR_BET = "CHECK_OR_BET"
    FOLD_CALL_OR_RAISE = "FOLD_CALL_OR_RAISE"


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
            decision_type = (
                self.decision_type
                if isinstance(self.decision_type, DecisionType)
                else DecisionType(str(self.decision_type).strip().upper())
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
        available = tuple(
            dict.fromkeys(
                _required_text(action, "available_action").upper()
                for action in self.available_actions
            )
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

        ratio = amount / pot if amount is not None and pot not in (None, 0) else None
        object.__setattr__(self, "size_ratio", ratio)
        object.__setattr__(self, "is_valid", bool(self.is_valid))
        object.__setattr__(self, "is_multiway", bool(self.is_multiway))
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
