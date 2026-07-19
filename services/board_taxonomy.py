from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

RANK_VALUE = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7,
    "8": 8, "9": 9, "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
}

CANONICAL_FAMILIES = (
    "High Rainbow Connected",
    "High Rainbow Semi Connected",
    "High Rainbow Disconnected",
    "High Two-tone Connected",
    "High Two-tone Semi Connected",
    "High Two-tone Disconnected",
    "High Monotone Connected",
    "High Monotone Semi Connected",
    "High Monotone Disconnected",
    "Medium Rainbow Connected",
    "Medium Rainbow Semi Connected",
    "Medium Rainbow Disconnected",
    "Medium Two-tone Connected",
    "Medium Two-tone Semi Connected",
    "Medium Two-tone Disconnected",
    "Medium Monotone Connected",
    "Medium Monotone Semi Connected",
    "Medium Monotone Disconnected",
    "Low Rainbow Connected",
    "Low Rainbow Semi Connected",
    "Low Rainbow Disconnected",
    "Low Two-tone Connected",
    "Low Two-tone Semi Connected",
    "Low Two-tone Disconnected",
    "Low Monotone Connected",
    "Low Monotone Semi Connected",
    "Low Monotone Disconnected",
    "Paired Rainbow Connected",
    "Paired Rainbow Semi Connected",
    "Paired Rainbow Disconnected",
    "Paired Two-tone Connected",
    "Paired Two-tone Semi Connected",
    "Paired Two-tone Disconnected",
    "Paired Monotone Connected",
    "Paired Monotone Semi Connected",
    "Paired Monotone Disconnected",
)

SUIT_SYMBOLS = {"♠": "s", "♥": "h", "♦": "d", "♣": "c"}

@dataclass(frozen=True, slots=True)
class BoardTexture:
    family: str
    height: str
    suit: str
    connectivity: str
    paired: bool
    high_card: str

def normalize_cards(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    for symbol, suit in SUIT_SYMBOLS.items():
        text = text.replace(symbol, suit)
    text = re.sub(r"(?i)10(?=[shdc])", "T", text)
    cards = re.findall(r"([2-9TJQKA])\s*([shdc])", text, flags=re.I)
    return [rank.upper() + suit.lower() for rank, suit in cards]

def _height(values: list[int], paired: bool) -> str:
    if paired:
        return "Paired"
    top = max(values)
    if top >= 11:
        return "High"
    if top >= 8:
        return "Medium"
    return "Low"

def _suit(cards: list[str]) -> str:
    unique = len({card[1] for card in cards[:3]})
    if unique == 1:
        return "Monotone"
    if unique == 2:
        return "Two-tone"
    return "Rainbow"

def _connectivity(values: list[int]) -> str:
    distinct = sorted(set(values), reverse=True)
    if len(distinct) < 2:
        return "Disconnected"
    candidates = [distinct]
    if 14 in distinct:
        candidates.append(sorted([1 if v == 14 else v for v in distinct], reverse=True))
    best_span = min(max(v) - min(v) for v in candidates)
    gaps = min(
        sum(max(0, a - b - 1) for a, b in zip(vs, vs[1:]))
        for vs in candidates
    )
    if best_span <= 4 and gaps <= 1:
        return "Connected"
    if best_span <= 5 and gaps <= 2:
        return "Semi Connected"
    return "Disconnected"

def classify_board(value: Any) -> BoardTexture:
    cards = normalize_cards(value)
    if len(cards) < 3:
        return BoardTexture("Unknown", "Unknown", "Unknown", "Unknown", False, "")
    cards = cards[:3]
    values = [RANK_VALUE[c[0]] for c in cards]
    paired = len(set(values)) < 3
    height = _height(values, paired)
    suit = _suit(cards)
    connectivity = _connectivity(values)
    family = f"{height} {suit} {connectivity}"
    high_card = max(cards, key=lambda c: RANK_VALUE[c[0]])[0]
    return BoardTexture(family, height, suit, connectivity, paired, high_card)

def board_family(value: Any) -> str:
    return classify_board(value).family

def simple_family(value: Any) -> str:
    texture = classify_board(value)
    if texture.family == "Unknown":
        return "Unknown"
    if texture.paired:
        return "Paired"
    if texture.high_card == "A":
        return "A-high Dynamic" if texture.connectivity != "Disconnected" or texture.suit != "Rainbow" else "A-high Dry"
    if texture.high_card in {"K", "Q", "J"}:
        return "K/Q/J-high Dynamic" if texture.connectivity != "Disconnected" or texture.suit != "Rainbow" else "K/Q/J-high Dry"
    if texture.height == "Medium":
        return "Mid Connected" if texture.connectivity != "Disconnected" else "Mid Dry"
    if texture.suit == "Monotone":
        return "Monotone Low"
    return "Low Dynamic" if texture.connectivity != "Disconnected" else "Low Dry"

def turn_transition(flop: Any, turn: Any) -> str:
    flop_cards = normalize_cards(flop)
    turn_cards = normalize_cards(turn)
    if not turn_cards:
        return "No Turn"
    card = turn_cards[-1]
    if card in flop_cards:
        return "Board Pair"
    flop_values = [RANK_VALUE[c[0]] for c in flop_cards[:3]]
    turn_value = RANK_VALUE[card[0]]
    if turn_value > max(flop_values, default=0):
        return "Overcard"
    suits = [c[1] for c in flop_cards[:3]]
    if suits.count(card[1]) >= 2:
        return "Flush Completes"
    before = classify_board(flop).connectivity
    after = _connectivity(flop_values + [turn_value])
    if before == "Disconnected" and after != "Disconnected":
        return "Straight Dynamic"
    return "Brick"
