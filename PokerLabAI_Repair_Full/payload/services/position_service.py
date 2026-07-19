from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional


@dataclass(frozen=True)
class PositionValidation:
    player_count: int
    button_seat: Optional[int]
    ring_size: int
    occupied_seats: tuple[int, ...]
    is_valid: bool
    message: str = ""


# Labels are listed clockwise after SB and BB, from earliest to latest position.
_PREFLOP_LABELS: dict[int, tuple[str, ...]] = {
    3: (),
    4: ("CO",),
    5: ("UTG", "CO"),
    6: ("UTG", "HJ", "CO"),
    7: ("UTG", "UTG+1", "HJ", "CO"),
    8: ("UTG", "UTG+1", "MP", "HJ", "CO"),
    9: ("UTG", "UTG+1", "MP", "MP+1", "HJ", "CO"),
}


def _seat_number(player: Mapping[str, object] | int) -> int:
    if isinstance(player, int):
        return player
    value = player.get("seat_no")
    if value is None:
        raise ValueError("seat_no is required")
    return int(value)


def validate_position_input(
    seats: Iterable[Mapping[str, object] | int],
    button_seat: Optional[int],
    max_seats: Optional[int],
) -> PositionValidation:
    occupied = tuple(sorted({_seat_number(player) for player in seats}))
    button = int(button_seat) if button_seat is not None else None
    largest_seat = max((*occupied, button or 0), default=0)
    ring_size = max(int(max_seats or 0), largest_seat)

    if not occupied:
        return PositionValidation(0, button, ring_size, occupied, False, "No occupied seats")
    if button is None:
        return PositionValidation(len(occupied), None, ring_size, occupied, False, "Button seat is missing")
    if ring_size < 2:
        return PositionValidation(len(occupied), button, ring_size, occupied, False, "Invalid ring size")
    if button not in occupied:
        return PositionValidation(
            len(occupied), button, ring_size, occupied, False,
            "Button seat is not present among dealt-in players",
        )
    if len(occupied) < 2:
        return PositionValidation(len(occupied), button, ring_size, occupied, False, "Fewer than two players")

    return PositionValidation(len(occupied), button, ring_size, occupied, True)


def calculate_positions(
    seats: Iterable[Mapping[str, object] | int],
    button_seat: Optional[int],
    max_seats: Optional[int],
) -> dict[int, str]:
    """Return seat -> position for 2-9 handed Hold'em.

    The button is deliberately excluded from the clockwise walk. This prevents
    BTN from being visited again and overwritten as CO, the defect repaired by
    this module.
    """
    seat_items = list(seats)
    validation = validate_position_input(seat_items, button_seat, max_seats)
    if not validation.is_valid:
        return {}

    occupied = set(validation.occupied_seats)
    button = int(validation.button_seat)
    ring_size = validation.ring_size
    player_count = validation.player_count

    # range(1, ring_size), not ring_size + 1: offset ring_size is the button.
    clockwise = [
        ((button - 1 + offset) % ring_size) + 1
        for offset in range(1, ring_size)
    ]
    after_button = [seat for seat in clockwise if seat in occupied]

    positions: dict[int, str] = {button: "BTN"}

    if player_count == 2:
        positions[after_button[0]] = "BB"
        return positions

    positions[after_button[0]] = "SB"
    positions[after_button[1]] = "BB"

    remaining = after_button[2:]
    labels = _PREFLOP_LABELS.get(player_count)
    if labels is None or len(labels) != len(remaining):
        labels = tuple(f"EP{i + 1}" for i in range(len(remaining)))

    positions.update(dict(zip(remaining, labels)))
    return positions
