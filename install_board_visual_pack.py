from __future__ import annotations

from pathlib import Path
import shutil
import textwrap

ROOT = Path(__file__).resolve().parent

FILES = {
    ROOT / "services" / "board_taxonomy.py": r"""
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
""",
    ROOT / "services" / "size_bucket_service.py": r"""
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
""",
    ROOT / "ui" / "analytics_palette.py": r"""
from __future__ import annotations

import re
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import QComboBox, QTableWidget, QTableWidgetItem

BOARD_COLORS = {
    "High": "#2563eb",
    "Medium": "#16a34a",
    "Low": "#64748b",
    "Paired": "#7c3aed",
    "Monotone": "#dc2626",
    "Two-tone": "#d97706",
    "Rainbow": "#059669",
}
SIZE_RANGES = (
    (20, "#64748b"), (30, "#3b82f6"), (40, "#2563eb"),
    (50, "#22c55e"), (60, "#16a34a"), (75, "#eab308"),
    (90, "#f59e0b"), (110, "#f97316"), (140, "#ef4444"),
    (175, "#dc2626"), (225, "#a855f7"), (10_000, "#7e22ce"),
)

def _contrast(hex_color: str) -> str:
    color = QColor(hex_color)
    luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
    return "#0b1220" if luminance > 165 else "#ffffff"

def board_color(text: str) -> str | None:
    value = str(text or "")
    for token in ("Paired", "Monotone", "Two-tone", "Rainbow", "High", "Medium", "Low"):
        if token.lower() in value.lower():
            return BOARD_COLORS[token]
    return None

def size_color(text: str) -> str | None:
    value = str(text or "")
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*%", value)
    if not match:
        if "all-in" in value.lower():
            return "#111827"
        return None
    number = float(match.group(1))
    for limit, color in SIZE_RANGES:
        if number <= limit:
            return color
    return SIZE_RANGES[-1][1]

def confidence_color(text: str) -> str | None:
    value = str(text or "").lower()
    if any(x in value for x in ("very high", "çok yüksek", "diamond")):
        return "#0ea5e9"
    if any(x in value for x in ("high", "yüksek")):
        return "#22c55e"
    if any(x in value for x in ("medium", "orta")):
        return "#eab308"
    if any(x in value for x in ("low", "düşük")):
        return "#ef4444"
    return None

def exploit_color(number: float) -> str:
    value = abs(float(number))
    if value < 5:
        return "#64748b"
    if value < 10:
        return "#86efac"
    if value < 20:
        return "#22c55e"
    if value < 30:
        return "#eab308"
    if value < 40:
        return "#f97316"
    return "#ef4444"

def style_item(item: QTableWidgetItem, semantic: str = "") -> None:
    text = item.text()
    color = None
    semantic_lower = semantic.lower()
    if "board" in semantic_lower or "texture" in semantic_lower or "aile" in semantic_lower:
        color = board_color(text)
    elif "size" in semantic_lower or "%" in text:
        color = size_color(text)
    elif "confidence" in semantic_lower or "güven" in semantic_lower:
        color = confidence_color(text)
    elif any(token in semantic_lower for token in ("delta", "edge", "exploit", "difference", "Δ".lower())):
        match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", "."))
        if match:
            color = exploit_color(float(match.group()))
    if color:
        item.setBackground(QBrush(QColor(color)))
        item.setForeground(QBrush(QColor(_contrast(color))))
        item.setData(Qt.ItemDataRole.UserRole + 20, color)

def style_table(table: QTableWidget, columns: list[tuple[str, str]] | None = None) -> None:
    headers = []
    if columns:
        headers = [f"{key} {label}" for key, label in columns]
    else:
        for col in range(table.columnCount()):
            h = table.horizontalHeaderItem(col)
            headers.append(h.text() if h else "")
    for row in range(table.rowCount()):
        for col in range(table.columnCount()):
            item = table.item(row, col)
            if item:
                style_item(item, headers[col] if col < len(headers) else "")

def style_combo(combo: QComboBox) -> None:
    model = combo.model()
    for index in range(combo.count()):
        text = combo.itemText(index)
        color = board_color(text) or size_color(text)
        if color:
            model.setData(model.index(index, 0), QColor(color), Qt.ItemDataRole.BackgroundRole)
            model.setData(model.index(index, 0), QColor(_contrast(color)), Qt.ItemDataRole.ForegroundRole)
""",
    ROOT / "sitecustomize.py": r"""
from __future__ import annotations

def _install_service_compatibility() -> None:
    try:
        from services.board_taxonomy import board_family, simple_family, turn_transition
        from services.size_bucket_service import open_bucket
        from services.size_board_strategy_service import SizeBoardStrategyService

        SizeBoardStrategyService._texture_family = staticmethod(board_family)
        SizeBoardStrategyService._simple_flop_family = staticmethod(simple_family)
        SizeBoardStrategyService._turn_transition = staticmethod(turn_transition)

        for method_name in ("_size_bucket", "_study_size_bucket"):
            if hasattr(SizeBoardStrategyService, method_name):
                setattr(
                    SizeBoardStrategyService,
                    method_name,
                    staticmethod(lambda value, *_args, **_kwargs: open_bucket(float(value or 0))),
                )
    except Exception:
        pass

def _install_ui_hooks() -> None:
    try:
        from PySide6.QtWidgets import QComboBox, QTableWidget
        from ui.analytics_palette import style_combo, style_table

        original_show_popup = QComboBox.showPopup
        def colored_show_popup(self):
            try:
                style_combo(self)
            except Exception:
                pass
            return original_show_popup(self)
        QComboBox.showPopup = colored_show_popup

        original_resize_rows = QTableWidget.resizeRowsToContents
        def colored_resize_rows(self):
            try:
                style_table(self)
            except Exception:
                pass
            return original_resize_rows(self)
        QTableWidget.resizeRowsToContents = colored_resize_rows
    except Exception:
        pass

_install_service_compatibility()
_install_ui_hooks()
""",
    ROOT / "verify_board_visual_pack.py": r"""
from __future__ import annotations

from services.board_taxonomy import board_family, simple_family
from services.size_bucket_service import open_bucket, postflop_bucket

tests = [
    ("Ah Kd 7c", "High Rainbow Disconnected"),
    ("9h 8h 7c", "Medium Two-tone Connected"),
    ("6s 6d 2c", "Paired Rainbow Disconnected"),
]

for board, expected in tests:
    actual = board_family(board)
    print(f"{board:12} -> {actual}")
    assert actual == expected, (board, actual, expected)

print("Open buckets:", [open_bucket(v) for v in (2.0, 2.25, 2.5, 3.0, 3.5, 4.0, 4.5)])
print("Postflop:", [postflop_bucket(v) for v in (20, 30, 40, 50, 60, 75, 90, 110, 140, 175, 225, 250)])
print("Simple:", simple_family("Ah Kd 7c"))
print("OK: Board + Size + Visual pack aktif.")
""",
}

def main() -> int:
    backup_root = ROOT / "_backup_before_board_visual_pack"
    backup_root.mkdir(exist_ok=True)

    for target, content in FILES.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            relative = target.relative_to(ROOT)
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        target.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
        print(f"YAZILDI: {target.relative_to(ROOT)}")

    for base in (ROOT / "services", ROOT / "ui", ROOT):
        if not base.exists():
            continue
        for cache in base.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)

    print()
    print("Kurulum tamamlandı.")
    print("Kontrol: python verify_board_visual_pack.py")
    print("Başlat:  python main.py")
    print(f"Yedek:    {backup_root}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
