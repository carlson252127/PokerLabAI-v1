from __future__ import annotations

import re
from pathlib import Path

import duckdb
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


SUIT_SYMBOLS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
RED_SUITS = {"h", "d"}


def normalize_board(board: str | None) -> str:
    cards = re.findall(r"([2-9TJQKA])([shdc])", str(board or ""), re.I)
    return " ".join(
        f"{rank.upper()}{suit.lower()}" for rank, suit in cards[:3]
    )


class PokerCard(QFrame):
    def __init__(self, card: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(54, 72)
        self.setObjectName("VisualPokerCard")

        match = re.fullmatch(r"([2-9TJQKA])([shdc])", card, re.I)
        rank, suit = match.groups() if match else ("?", "s")
        suit = suit.lower()
        foreground = "#dc2626" if suit in RED_SUITS else "#111827"

        self.setStyleSheet(
            f"""
            QFrame#VisualPokerCard {{
                background: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 7px;
            }}
            QLabel {{
                background: transparent;
                color: {foreground};
                border: none;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(0)

        rank_label = QLabel(rank.upper())
        rank_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rank_label.setStyleSheet(
            f"font-size: 24px; font-weight: 800; color: {foreground};"
        )

        suit_label = QLabel(SUIT_SYMBOLS.get(suit, "?"))
        suit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        suit_label.setStyleSheet(
            f"font-size: 27px; font-weight: 700; color: {foreground};"
        )

        layout.addWidget(rank_label)
        layout.addWidget(suit_label)


class BoardTile(QFrame):
    clicked = Signal(str)

    def __init__(
        self,
        board: str,
        hand_count: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.board = normalize_board(board)
        self.setObjectName("VisualBoardTile")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.setMinimumWidth(205)
        self.setFixedHeight(118)
        self.setToolTip(
            f"{self.board}\n{hand_count:,} el\nFiltrelemek için tıkla"
        )
        self.setStyleSheet(
            """
            QFrame#VisualBoardTile {
                background: #151b26;
                border: 1px solid #30394a;
                border-radius: 10px;
            }
            QFrame#VisualBoardTile:hover {
                background: #1b2534;
                border: 1px solid #3b82f6;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 7)
        root.setSpacing(5)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(5)
        cards_row.addStretch()

        for card in self.board.split():
            cards_row.addWidget(PokerCard(card))

        cards_row.addStretch()
        root.addLayout(cards_row)

        footer = QLabel(f"{self.board}  •  {hand_count:,} el")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet(
            "font-size: 11px; color: #aeb8c8; font-weight: 600;"
        )
        root.addWidget(footer)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.board)
        super().mousePressEvent(event)


class VisualBoardBrowser(QFrame):
    board_selected = Signal(str)

    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database_path = str(Path(database_path))
        self.setObjectName("VisualBoardBrowser")
        self.setStyleSheet(
            """
            QFrame#VisualBoardBrowser {
                background: #111722;
                border: 1px solid #2d3748;
                border-radius: 12px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(13, 11, 13, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(1)

        title = QLabel("Görsel Board Listesi")
        title.setStyleSheet(
            "font-size: 15px; font-weight: 800; color: #f1f5f9;"
        )
        subtitle = QLabel(
            "Gerçek veritabanındaki sık floplar • Board’a tıklayarak filtrele"
        )
        subtitle.setStyleSheet("font-size: 11px; color: #94a3b8;")

        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self.limit_combo = QComboBox()
        for value in (12, 20, 30, 50):
            self.limit_combo.addItem(f"{value} board", value)
        self.limit_combo.setCurrentIndex(1)
        self.limit_combo.setFixedWidth(105)

        self.reload_button = QPushButton("Yenile")
        self.reload_button.setFixedWidth(75)
        self.reload_button.clicked.connect(self.reload)

        header.addWidget(self.limit_combo)
        header.addWidget(self.reload_button)
        root.addLayout(header)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 11px; color: #94a3b8;")
        root.addWidget(self.status_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setFixedHeight(140)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.container = QWidget()
        self.board_layout = QHBoxLayout(self.container)
        self.board_layout.setContentsMargins(0, 0, 0, 0)
        self.board_layout.setSpacing(9)
        self.board_layout.addStretch()

        self.scroll.setWidget(self.container)
        root.addWidget(self.scroll)

        self.limit_combo.currentIndexChanged.connect(self.reload)
        self.reload()

    def _clear_tiles(self) -> None:
        while self.board_layout.count():
            item = self.board_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def reload(self) -> None:
        self._clear_tiles()
        limit = int(self.limit_combo.currentData() or 20)

        try:
            with duckdb.connect(self.database_path, read_only=True) as con:
                rows = con.execute(
                    """
                    SELECT TRIM(flop) AS board, COUNT(*) AS hand_count
                    FROM hands
                    WHERE flop IS NOT NULL
                      AND TRIM(flop) <> ''
                    GROUP BY TRIM(flop)
                    ORDER BY hand_count DESC, board
                    LIMIT ?
                    """,
                    [limit],
                ).fetchall()

            shown = 0
            for board, hand_count in rows:
                normalized = normalize_board(str(board or ""))
                if len(normalized.split()) != 3:
                    continue
                tile = BoardTile(normalized, int(hand_count or 0))
                tile.clicked.connect(self.board_selected)
                self.board_layout.addWidget(tile)
                shown += 1

            self.board_layout.addStretch()
            self.status_label.setText(
                f"{shown} gerçek flop gösteriliyor."
                if shown else "Gösterilecek flop bulunamadı."
            )
        except Exception as exc:
            self.board_layout.addStretch()
            self.status_label.setText(
                f"Board listesi yüklenemedi: {type(exc).__name__}: {exc}"
            )
