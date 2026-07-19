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
