from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class BoardClassifier:
    RANK_VALUES = {
        "2": 2,
        "3": 3,
        "4": 4,
        "5": 5,
        "6": 6,
        "7": 7,
        "8": 8,
        "9": 9,
        "T": 10,
        "J": 11,
        "Q": 12,
        "K": 13,
        "A": 14,
    }

    @classmethod
    def classify(cls, flop: str | None) -> dict[str, Any]:
        cards = re.findall(
            r"([2-9TJQKA])([shdcSHDC])",
            str(flop or ""),
        )

        if len(cards) < 3:
            return {
                "texture": "UNKNOWN",
                "high_card": "UNKNOWN",
                "suit_type": "UNKNOWN",
                "paired_type": "UNKNOWN",
                "connected": False,
            }

        ranks = [rank.upper() for rank, _ in cards[:3]]
        suits = [suit.lower() for _, suit in cards[:3]]
        values = sorted(
            [cls.RANK_VALUES[rank] for rank in ranks],
            reverse=True,
        )

        high_card = {
            14: "A_HIGH",
            13: "K_HIGH",
            12: "Q_HIGH",
            11: "J_HIGH",
            10: "T_HIGH",
        }.get(values[0], "LOW")

        suit_count = len(set(suits))
        suit_type = {
            1: "MONOTONE",
            2: "TWO_TONE",
            3: "RAINBOW",
        }.get(suit_count, "UNKNOWN")

        rank_count = len(set(ranks))

        if rank_count == 1:
            paired_type = "TRIPS"
        elif rank_count == 2:
            paired_type = "PAIRED"
        else:
            paired_type = "UNPAIRED"

        unique_values = sorted(set(values))
        connected = False

        if len(unique_values) == 3:
            gaps = [
                unique_values[index + 1] - unique_values[index]
                for index in range(2)
            ]
            connected = max(gaps) <= 2

        if paired_type in {"PAIRED", "TRIPS"}:
            texture = paired_type
        else:
            texture = f"{high_card}_{suit_type}"

        if connected:
            texture += "_CONNECTED"

        return {
            "texture": texture,
            "high_card": high_card,
            "suit_type": suit_type,
            "paired_type": paired_type,
            "connected": connected,
        }

    @classmethod
    def matches(
        cls,
        flop: str | None,
        texture_filter: str,
    ) -> bool:
        if not texture_filter:
            return True

        data = cls.classify(flop)

        if texture_filter in {
            "RAINBOW",
            "TWO_TONE",
            "MONOTONE",
        }:
            return data["suit_type"] == texture_filter

        if texture_filter in {"PAIRED", "TRIPS"}:
            return data["paired_type"] == texture_filter

        if texture_filter == "CONNECTED":
            return bool(data["connected"])

        return data["texture"] == texture_filter



def normalize_flop(value: str | None) -> str:
    cards = re.findall(r"([2-9TJQKA])([shdcSHDC])", str(value or ""))
    return " ".join(f"{rank.upper()}{suit.lower()}" for rank, suit in cards[:3])


def friendly_texture(texture: str) -> str:
    special = {
        "PAIRED": "Paired Board",
        "TRIPS": "Trips Board",
        "CONNECTED": "Connected Board",
        "UNKNOWN": "Unknown Board",
    }
    if texture in special:
        return special[texture]
    return (
        texture.replace("A_HIGH", "A-High")
        .replace("K_HIGH", "K-High")
        .replace("Q_HIGH", "Q-High")
        .replace("J_HIGH", "J-High")
        .replace("T_HIGH", "T-High")
        .replace("LOW", "Low")
        .replace("TWO_TONE", "Two-Tone")
        .replace("RAINBOW", "Rainbow")
        .replace("MONOTONE", "Monotone")
        .replace("CONNECTED", "Connected")
        .replace("_", " ")
        .title()
        .replace("A-High", "A-High")
        .replace("K-High", "K-High")
        .replace("Q-High", "Q-High")
        .replace("J-High", "J-High")
        .replace("T-High", "T-High")
    )


class MiniPokerCard(QFrame):
    SUITS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}

    def __init__(self, card: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        match = re.fullmatch(r"([2-9TJQKA])([shdc])", card, re.I)
        rank, suit = match.groups() if match else ("?", "s")
        suit = suit.lower()
        color = "#dc2626" if suit in {"h", "d"} else "#111827"
        self.setFixedSize(58, 78)
        self.setObjectName("MiniPokerCard")
        self.setStyleSheet(
            f"""
            QFrame#MiniPokerCard {{
                background: #f8fafc;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
            }}
            QLabel {{ color: {color}; background: transparent; border: none; }}
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 2, 3, 2)
        layout.setSpacing(0)
        rank_label = QLabel(rank.upper())
        rank_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rank_label.setStyleSheet("font-size: 25px; font-weight: 900;")
        suit_label = QLabel(self.SUITS.get(suit, "?"))
        suit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        suit_label.setStyleSheet("font-size: 29px; font-weight: 800;")
        layout.addWidget(rank_label)
        layout.addWidget(suit_label)


class BoardFamilyCard(QFrame):
    selected = Signal(str, str)

    def __init__(self, family: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.family = family
        self.setObjectName("BoardFamilyCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(245)
        self.setMinimumHeight(174)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setToolTip("Kategori ile filtrelemek için tıkla")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)

        title = QLabel(str(family.get("label") or "Board Family"))
        title.setObjectName("BoardFamilyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        cards = QHBoxLayout()
        cards.setSpacing(6)
        cards.addStretch()
        for card in str(family.get("representative") or "").split():
            cards.addWidget(MiniPokerCard(card))
        cards.addStretch()
        layout.addLayout(cards)

        hands = int(family.get("hands") or 0)
        rep_hands = int(family.get("representative_hands") or 0)
        meta = QLabel(f"{hands:,} el  •  temsilî board {rep_hands:,} el".replace(",", "."))
        meta.setObjectName("BoardFamilyMeta")
        meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(meta)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(
                str(self.family.get("texture") or ""),
                str(self.family.get("representative") or ""),
            )
        super().mousePressEvent(event)


class BoardExplorerWorker(QObject):
    finished = Signal(dict, dict, list, int, list)
    failed = Signal(str)

    def __init__(
        self,
        database_path: str,
        mode: str,
        entity_name: str,
        site: str,
        stakes: str,
        texture: str,
        flop_text: str,
        turn_text: str,
        river_text: str,
        scan_limit: int = 20000,
        display_limit: int = 300,
    ) -> None:
        super().__init__()

        self.database_path = database_path
        self.mode = mode
        self.entity_name = entity_name
        self.site = site
        self.stakes = stakes
        self.texture = texture
        self.flop_text = flop_text
        self.turn_text = turn_text
        self.river_text = river_text
        self.scan_limit = scan_limit
        self.display_limit = display_limit

    @Slot()
    def run(self) -> None:
        try:
            with duckdb.connect(
                self.database_path,
                read_only=True,
            ) as con:
                entity_rows = self._load_rows(
                    con,
                    entity_only=self.mode
                    in {"PLAYER", "ALIAS", "COMPARE"},
                )

                entity_filtered = self._filter_texture(
                    entity_rows
                )

                pool_filtered: list[dict[str, Any]] = []

                if self.mode == "COMPARE":
                    pool_rows = self._load_rows(
                        con,
                        entity_only=False,
                    )
                    pool_filtered = self._filter_texture(
                        pool_rows
                    )

                entity_summary = self._summary(
                    con,
                    entity_filtered,
                    entity_only=self.mode
                    in {"PLAYER", "ALIAS", "COMPARE"},
                )

                pool_summary = (
                    self._summary(
                        con,
                        pool_filtered,
                        entity_only=False,
                    )
                    if self.mode == "COMPARE"
                    else {}
                )

            self.finished.emit(
                entity_summary,
                pool_summary,
                entity_filtered[: self.display_limit],
                len(entity_filtered),
                self._family_summaries(entity_filtered),
            )

        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )


    def _family_summaries(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        families: dict[str, dict[str, Any]] = {}

        for row in rows:
            texture = str(row.get("texture") or "UNKNOWN")
            flop = normalize_flop(str(row.get("flop") or ""))
            if len(flop.split()) != 3:
                continue

            family = families.setdefault(
                texture,
                {
                    "texture": texture,
                    "hands": 0,
                    "boards": {},
                },
            )
            family["hands"] += 1
            family["boards"][flop] = family["boards"].get(flop, 0) + 1

        result: list[dict[str, Any]] = []
        for family in families.values():
            ranked = sorted(
                family["boards"].items(),
                key=lambda item: (-item[1], item[0]),
            )
            if not ranked:
                continue
            result.append(
                {
                    "texture": family["texture"],
                    "label": friendly_texture(family["texture"]),
                    "hands": int(family["hands"]),
                    "representative": ranked[0][0],
                    "representative_hands": int(ranked[0][1]),
                    "examples": [board for board, _ in ranked[:4]],
                }
            )

        result.sort(key=lambda item: (-item["hands"], item["label"]))
        return result

    def _base_clauses(self) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if self.site:
            clauses.append("h.site = ?")
            params.append(self.site)

        if self.stakes:
            clauses.append("h.stakes = ?")
            params.append(self.stakes)

        if self.flop_text:
            clauses.append(
                "LOWER(COALESCE(h.flop, '')) LIKE ?"
            )
            params.append(f"%{self.flop_text.lower()}%")

        if self.turn_text:
            clauses.append(
                "LOWER(COALESCE(h.turn, '')) LIKE ?"
            )
            params.append(f"%{self.turn_text.lower()}%")

        if self.river_text:
            clauses.append(
                "LOWER(COALESCE(h.river, '')) LIKE ?"
            )
            params.append(f"%{self.river_text.lower()}%")

        return clauses, params

    def _entity_clause(
        self,
    ) -> tuple[str, list[Any]]:
        if self.mode == "PLAYER":
            return (
                """
                EXISTS (
                    SELECT 1
                    FROM hand_players ep
                    WHERE ep.hand_id = h.hand_id
                      AND ep.player_name = ?
                )
                """,
                [self.entity_name],
            )

        if self.mode in {"ALIAS", "COMPARE"}:
            return (
                """
                EXISTS (
                    SELECT 1
                    FROM hand_players ep
                    JOIN player_aliases pa
                      ON pa.player_name = ep.player_name
                    WHERE ep.hand_id = h.hand_id
                      AND pa.alias_name = ?
                )
                """,
                [self.entity_name],
            )

        return "TRUE", []

    def _load_rows(
        self,
        con: duckdb.DuckDBPyConnection,
        entity_only: bool,
    ) -> list[dict[str, Any]]:
        clauses, params = self._base_clauses()

        if entity_only:
            condition, condition_params = (
                self._entity_clause()
            )
            clauses.append(condition)
            params.extend(condition_params)

        where_sql = (
            "WHERE " + " AND ".join(clauses)
            if clauses
            else ""
        )

        rows = con.execute(
            f"""
            SELECT
                h.hand_id,
                h.site,
                h.stakes,
                h.table_name,
                h.played_at,
                h.flop,
                h.turn,
                h.river,
                h.pot,
                h.rake,
                h.source_file
            FROM hands h
            {where_sql}
            ORDER BY h.played_at DESC NULLS LAST
            LIMIT {self.scan_limit}
            """,
            params,
        ).fetchall()

        result: list[dict[str, Any]] = []

        for row in rows:
            texture_data = BoardClassifier.classify(
                row[5]
            )

            result.append(
                {
                    "hand_id": str(row[0]),
                    "site": row[1],
                    "stakes": row[2],
                    "table_name": row[3],
                    "played_at": row[4],
                    "flop": row[5],
                    "texture": texture_data["texture"],
                    "turn": row[6],
                    "river": row[7],
                    "pot": row[8],
                    "rake": row[9],
                    "source_file": row[10],
                }
            )

        return result

    def _filter_texture(
        self,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not self.texture:
            return rows

        return [
            row
            for row in rows
            if BoardClassifier.matches(
                row.get("flop"),
                self.texture,
            )
        ]

    def _entity_player_condition(
        self,
        alias: str = "a",
    ) -> tuple[str, list[Any]]:
        if self.mode == "PLAYER":
            return (
                f"{alias}.player_name = ?",
                [self.entity_name],
            )

        if self.mode in {"ALIAS", "COMPARE"}:
            return (
                f"""
                EXISTS (
                    SELECT 1
                    FROM player_aliases pa
                    WHERE pa.player_name = {alias}.player_name
                      AND pa.alias_name = ?
                )
                """,
                [self.entity_name],
            )

        return "TRUE", []

    def _summary(
        self,
        con: duckdb.DuckDBPyConnection,
        rows: list[dict[str, Any]],
        entity_only: bool,
    ) -> dict[str, Any]:
        hand_ids = [
            row["hand_id"]
            for row in rows
        ]

        if not hand_ids:
            return {
                "hands": 0,
                "flop_bet": 0.0,
                "turn_bet": 0.0,
                "river_bet": 0.0,
                "fold": 0.0,
                "avg_pot": 0.0,
                "avg_rake": 0.0,
            }

        placeholders = ",".join(
            "?" for _ in hand_ids
        )

        action_clause = "TRUE"
        action_params: list[Any] = []

        if entity_only:
            action_clause, action_params = (
                self._entity_player_condition("a")
            )

        action_rows = con.execute(
            f"""
            SELECT
                a.street,
                a.action,
                COUNT(*)
            FROM actions a
            WHERE a.hand_id IN ({placeholders})
              AND ({action_clause})
            GROUP BY a.street, a.action
            """,
            hand_ids + action_params,
        ).fetchall()

        counts = {
            (str(street), str(action)): int(count)
            for street, action, count in action_rows
        }

        street_totals = {
            street: sum(
                count
                for (row_street, _), count
                in counts.items()
                if row_street == street
            )
            for street in (
                "FLOP",
                "TURN",
                "RIVER",
            )
        }

        all_actions = sum(counts.values())
        all_folds = sum(
            count
            for (_, action), count in counts.items()
            if action == "FOLD"
        )

        def rate(
            street: str,
            action: str,
        ) -> float:
            denominator = street_totals.get(
                street,
                0,
            )

            return (
                counts.get((street, action), 0)
                / denominator
                * 100.0
                if denominator
                else 0.0
            )

        pots = [
            float(row["pot"])
            for row in rows
            if row.get("pot") is not None
        ]
        rakes = [
            float(row["rake"])
            for row in rows
            if row.get("rake") is not None
        ]

        return {
            "hands": len(rows),
            "flop_bet": rate("FLOP", "BET"),
            "turn_bet": rate("TURN", "BET"),
            "river_bet": rate("RIVER", "BET"),
            "fold": (
                all_folds / all_actions * 100.0
                if all_actions
                else 0.0
            ),
            "avg_pot": (
                sum(pots) / len(pots)
                if pots
                else 0.0
            ),
            "avg_rake": (
                sum(rakes) / len(rakes)
                if rakes
                else 0.0
            ),
        }


class BoardExplorer(QWidget):
    DISPLAY_LIMIT = 300

    BOARD_TEXTURES = [
        ("Tüm Boardlar", ""),
        ("A-High Rainbow", "A_HIGH_RAINBOW"),
        ("A-High Two-Tone", "A_HIGH_TWO_TONE"),
        ("A-High Monotone", "A_HIGH_MONOTONE"),
        ("K-High Rainbow", "K_HIGH_RAINBOW"),
        ("K-High Two-Tone", "K_HIGH_TWO_TONE"),
        ("Q-High Rainbow", "Q_HIGH_RAINBOW"),
        ("Low Rainbow", "LOW_RAINBOW"),
        ("Low Two-Tone", "LOW_TWO_TONE"),
        ("Paired", "PAIRED"),
        ("Trips", "TRIPS"),
        ("Connected", "CONNECTED"),
        ("Rainbow", "RAINBOW"),
        ("Two-Tone", "TWO_TONE"),
        ("Monotone", "MONOTONE"),
    ]

    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = str(Path(database_path))
        self.search_thread: QThread | None = None
        self.search_worker: BoardExplorerWorker | None = None
        self.filters_loaded = False

        self._build_ui()
        QTimer.singleShot(0, self._initial_load)

    def _initial_load(self) -> None:
        self.refresh_filters()
        if self.search_thread is None:
            self.run_search()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(13)

        title = QLabel("Board Explorer 3.0")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Pool, oyuncu veya alias grubunu veritabanı migrationı "
            "olmadan anlık board texture ile analiz et."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName("BoardFilters")

        grid = QGridLayout(filters)
        grid.setContentsMargins(15, 15, 15, 15)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(9)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Pool", "POOL")
        self.mode_combo.addItem("Player", "PLAYER")
        self.mode_combo.addItem("Alias Group", "ALIAS")
        self.mode_combo.addItem("Alias vs Pool", "COMPARE")
        self.mode_combo.currentIndexChanged.connect(
            self._mode_changed
        )

        self.entity_combo = QComboBox()
        self.entity_combo.setEnabled(False)
        self.entity_combo.setMinimumWidth(190)

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")

        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.texture_combo = QComboBox()
        for label, value in self.BOARD_TEXTURES:
            self.texture_combo.addItem(
                label,
                value,
            )

        self.flop_input = QLineEdit()
        self.flop_input.setPlaceholderText(
            "Flop: Ah Kd 7s"
        )

        self.turn_input = QLineEdit()
        self.turn_input.setPlaceholderText(
            "Turn: 2c"
        )

        self.river_input = QLineEdit()
        self.river_input.setPlaceholderText(
            "River: Qh"
        )

        self.load_entities_button = QPushButton(
            "Oyuncu/Alias Yükle"
        )
        self.search_button = QPushButton(
            "Analiz Et"
        )
        self.clear_button = QPushButton(
            "Temizle"
        )

        self.load_entities_button.clicked.connect(
            self.load_entities
        )
        self.search_button.clicked.connect(
            self.run_search
        )
        self.clear_button.clicked.connect(
            self.clear_filters
        )

        labels = [
            "Mod",
            "Oyuncu / Alias",
            "Site",
            "Stakes",
            "Board",
            "Flop",
            "Turn",
            "River",
        ]

        widgets = [
            self.mode_combo,
            self.entity_combo,
            self.site_combo,
            self.stakes_combo,
            self.texture_combo,
            self.flop_input,
            self.turn_input,
            self.river_input,
        ]

        for index, (label, widget) in enumerate(
            zip(labels, widgets)
        ):
            grid.addWidget(
                QLabel(label),
                0,
                index,
            )
            grid.addWidget(
                widget,
                1,
                index,
            )

        buttons = QHBoxLayout()
        buttons.addWidget(
            self.load_entities_button
        )
        buttons.addWidget(
            self.search_button
        )
        buttons.addWidget(
            self.clear_button
        )
        buttons.addStretch()

        grid.addLayout(
            buttons,
            2,
            0,
            1,
            8,
        )

        root.addWidget(filters)

        family_frame = QFrame()
        family_frame.setObjectName("BoardFamilyPanel")
        family_layout = QVBoxLayout(family_frame)
        family_layout.setContentsMargins(13, 11, 13, 11)
        family_layout.setSpacing(7)

        family_header = QHBoxLayout()
        family_title = QLabel("Board Kategorileri")
        family_title.setObjectName("BoardFamilyPanelTitle")
        family_subtitle = QLabel("Her kategori için en sık temsilî board ve kategori el sayısı")
        family_subtitle.setObjectName("PageSubtitle")
        family_header.addWidget(family_title)
        family_header.addSpacing(10)
        family_header.addWidget(family_subtitle)
        family_header.addStretch()
        family_layout.addLayout(family_header)

        self.family_scroll = QScrollArea()
        self.family_scroll.setWidgetResizable(True)
        self.family_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.family_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.family_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.family_scroll.setFixedHeight(202)

        self.family_container = QWidget()
        self.family_cards_layout = QHBoxLayout(self.family_container)
        self.family_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.family_cards_layout.setSpacing(10)
        self.family_placeholder = QLabel("Analiz Et düğmesine basınca kategori kartları burada görünecek.")
        self.family_placeholder.setObjectName("PageSubtitle")
        self.family_cards_layout.addWidget(self.family_placeholder)
        self.family_cards_layout.addStretch()
        self.family_scroll.setWidget(self.family_container)
        family_layout.addWidget(self.family_scroll)
        root.addWidget(family_frame)

        cards = QHBoxLayout()
        cards.setSpacing(10)

        self.hands_card = self._card(
            "Hands",
            "0",
        )
        self.flop_bet_card = self._card(
            "Flop Bet",
            "0.00%",
        )
        self.turn_bet_card = self._card(
            "Turn Bet",
            "0.00%",
        )
        self.river_bet_card = self._card(
            "River Bet",
            "0.00%",
        )
        self.fold_card = self._card(
            "Fold",
            "0.00%",
        )
        self.avg_pot_card = self._card(
            "Ort. Pot",
            "0.00",
        )

        for card in (
            self.hands_card,
            self.flop_bet_card,
            self.turn_bet_card,
            self.river_bet_card,
            self.fold_card,
            self.avg_pot_card,
        ):
            cards.addWidget(card)

        root.addLayout(cards)

        self.compare_label = QLabel("")
        self.compare_label.setObjectName(
            "CompareSummary"
        )
        self.compare_label.setWordWrap(True)
        self.compare_label.hide()

        root.addWidget(self.compare_label)

        self.status_label = QLabel(
            "Filtreleri seçip Analiz Et düğmesine bas."
        )
        self.status_label.setObjectName(
            "PageSubtitle"
        )

        root.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels(
            [
                "Hand ID",
                "Site",
                "Stakes",
                "Table",
                "Tarih",
                "Flop",
                "Texture",
                "Turn",
                "River",
                "Pot",
                "Rake",
                "Kaynak",
            ]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            6,
            QHeaderView.ResizeMode.Stretch,
        )

        root.addWidget(
            self.table,
            1,
        )

        note = QLabel(
            "Texture sınıflandırması RAM'de yapılır; hands tablosunda "
            "flop_texture kolonu gerekmez."
        )
        note.setObjectName("PageSubtitle")
        note.setWordWrap(True)

        root.addWidget(note)

        self.setStyleSheet(
            """
            QFrame#BoardFilters {
                background: #171b24;
                border: 1px solid #303744;
                border-radius: 12px;
            }

            QFrame#BoardFamilyPanel {
                background: #111722;
                border: 1px solid #303744;
                border-radius: 12px;
            }

            QLabel#BoardFamilyPanelTitle {
                font-size: 16px;
                font-weight: 800;
            }

            QFrame#BoardFamilyCard {
                background: #1a202b;
                border: 1px solid #343d4d;
                border-radius: 11px;
            }

            QFrame#BoardFamilyCard:hover {
                background: #202a39;
                border: 1px solid #3b82f6;
            }

            QLabel#BoardFamilyTitle {
                color: #f1f5f9;
                font-size: 14px;
                font-weight: 800;
            }

            QLabel#BoardFamilyMeta {
                color: #aeb8c8;
                font-size: 11px;
                font-weight: 600;
            }

            QFrame#BoardCard {
                background: #1d222d;
                border: 1px solid #343b49;
                border-radius: 10px;
            }

            QLabel#BoardCardTitle {
                color: #9ca3af;
                font-size: 12px;
            }

            QLabel#BoardCardValue {
                font-size: 20px;
                font-weight: 800;
            }

            QLabel#CompareSummary {
                padding: 14px;
                background: #23262d;
                border: 1px solid #3b4658;
                border-radius: 10px;
                font-size: 14px;
                font-weight: 700;
            }
            """
        )

    def _card(
        self,
        title: str,
        value: str,
    ) -> QFrame:
        frame = QFrame()
        frame.setObjectName(
            "BoardCard"
        )

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            14,
            10,
            14,
            10,
        )

        title_label = QLabel(title)
        title_label.setObjectName(
            "BoardCardTitle"
        )

        value_label = QLabel(value)
        value_label.setObjectName(
            "BoardCardValue"
        )
        value_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        frame.value_label = value_label

        layout.addWidget(title_label)
        layout.addWidget(value_label)

        return frame

    def refresh_filters(self) -> None:
        if self.filters_loaded:
            return

        try:
            with duckdb.connect(
                self.database_path,
                read_only=True,
            ) as con:
                sites = con.execute(
                    """
                    SELECT DISTINCT site
                    FROM hands
                    WHERE site IS NOT NULL
                      AND site <> ''
                    ORDER BY site
                    """
                ).fetchall()

                stakes = con.execute(
                    """
                    SELECT DISTINCT stakes
                    FROM hands
                    WHERE stakes IS NOT NULL
                      AND stakes <> ''
                    ORDER BY stakes
                    """
                ).fetchall()

            for row in sites:
                self.site_combo.addItem(
                    str(row[0]),
                    str(row[0]),
                )

            for row in stakes:
                self.stakes_combo.addItem(
                    str(row[0]),
                    str(row[0]),
                )

            self.filters_loaded = True

        except Exception as exc:
            self.status_label.setText(
                f"Filtre hatası: "
                f"{type(exc).__name__}: {exc}"
            )

    def _mode_changed(self) -> None:
        mode = str(
            self.mode_combo.currentData()
        )
        self.entity_combo.setEnabled(
            mode != "POOL"
        )

        if mode == "POOL":
            self.entity_combo.clear()

    def load_entities(self) -> None:
        mode = str(
            self.mode_combo.currentData()
        )

        if mode == "POOL":
            QMessageBox.information(
                self,
                "Board Explorer",
                "Pool modunda oyuncu veya alias seçilmez.",
            )
            return

        try:
            with duckdb.connect(
                self.database_path,
                read_only=True,
            ) as con:
                if mode == "PLAYER":
                    rows = con.execute(
                        """
                        SELECT
                            player_name,
                            COUNT(*) AS hands
                        FROM hand_players
                        GROUP BY player_name
                        ORDER BY hands DESC
                        LIMIT 5000
                        """
                    ).fetchall()
                else:
                    alias_table_exists = bool(
                        con.execute(
                            """
                            SELECT COUNT(*)
                            FROM information_schema.tables
                            WHERE table_schema = 'main'
                              AND table_name = 'player_aliases'
                            """
                        ).fetchone()[0]
                    )

                    if not alias_table_exists:
                        rows = []
                    else:
                        rows = con.execute(
                            """
                            SELECT
                                pa.alias_name,
                                COUNT(DISTINCT hp.hand_id)
                                    AS hands
                            FROM player_aliases pa
                            LEFT JOIN hand_players hp
                              ON hp.player_name = pa.player_name
                            GROUP BY pa.alias_name
                            ORDER BY hands DESC
                            """
                        ).fetchall()

            self.entity_combo.clear()

            for name, hands in rows:
                self.entity_combo.addItem(
                    f"{name} "
                    f"({int(hands or 0):,} hands)",
                    str(name),
                )

            self.status_label.setText(
                f"{len(rows)} profil yüklendi."
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Profil Yükleme Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def run_search(self) -> None:
        if self.search_thread is not None:
            return

        mode = str(
            self.mode_combo.currentData()
        )
        entity_name = str(
            self.entity_combo.currentData()
            or ""
        )

        if mode != "POOL" and not entity_name:
            QMessageBox.information(
                self,
                "Board Explorer",
                "Önce oyuncu veya alias profilini yükleyip seç.",
            )
            return

        self.search_button.setEnabled(False)
        self.status_label.setText(
            "Board analizi hesaplanıyor…"
        )

        self.search_thread = QThread(self)
        self.search_worker = BoardExplorerWorker(
            database_path=self.database_path,
            mode=mode,
            entity_name=entity_name,
            site=str(
                self.site_combo.currentData()
                or ""
            ),
            stakes=str(
                self.stakes_combo.currentData()
                or ""
            ),
            texture=str(
                self.texture_combo.currentData()
                or ""
            ),
            flop_text=self.flop_input.text().strip(),
            turn_text=self.turn_input.text().strip(),
            river_text=self.river_input.text().strip(),
            scan_limit=20000,
            display_limit=self.DISPLAY_LIMIT,
        )

        self.search_worker.moveToThread(
            self.search_thread
        )

        self.search_thread.started.connect(
            self.search_worker.run
        )
        self.search_worker.finished.connect(
            self._search_finished
        )
        self.search_worker.failed.connect(
            self._search_failed
        )

        self.search_worker.finished.connect(
            self.search_thread.quit
        )
        self.search_worker.failed.connect(
            self.search_thread.quit
        )
        self.search_thread.finished.connect(
            self._cleanup_search
        )

        self.search_thread.start()

    @Slot(dict, dict, list, int, list)
    def _search_finished(
        self,
        entity_summary: dict,
        pool_summary: dict,
        rows: list,
        filtered_count: int,
        families: list,
    ) -> None:
        self._update_family_cards(families)
        self._update_cards(
            entity_summary
        )
        self._fill_table(rows)

        if pool_summary:
            self.compare_label.show()
            self.compare_label.setText(
                "Alias vs Pool Delta — "
                f"Flop Bet: "
                f"{entity_summary['flop_bet'] - pool_summary['flop_bet']:+.2f} | "
                f"Turn Bet: "
                f"{entity_summary['turn_bet'] - pool_summary['turn_bet']:+.2f} | "
                f"River Bet: "
                f"{entity_summary['river_bet'] - pool_summary['river_bet']:+.2f} | "
                f"Fold: "
                f"{entity_summary['fold'] - pool_summary['fold']:+.2f} | "
                f"Pool Hands: "
                f"{pool_summary['hands']:,}"
            )
        else:
            self.compare_label.hide()

        self.status_label.setText(
            f"{filtered_count:,} hand bulundu; "
            f"ilk {len(rows):,} hand gösteriliyor."
        )

    @Slot(str)
    def _search_failed(
        self,
        message: str,
    ) -> None:
        QMessageBox.critical(
            self,
            "Board Explorer Hatası",
            message,
        )
        self.status_label.setText(
            "Analiz başarısız."
        )

    def _cleanup_search(self) -> None:
        self.search_button.setEnabled(True)
        self.search_worker = None
        self.search_thread = None


    def _update_family_cards(self, families: list[dict[str, Any]]) -> None:
        while self.family_cards_layout.count():
            item = self.family_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not families:
            label = QLabel("Bu filtrelerde board kategorisi bulunamadı.")
            label.setObjectName("PageSubtitle")
            self.family_cards_layout.addWidget(label)
            self.family_cards_layout.addStretch()
            return

        for family in families:
            card = BoardFamilyCard(family, self)
            card.selected.connect(self._family_selected)
            self.family_cards_layout.addWidget(card)

        self.family_cards_layout.addStretch()

    @Slot(str, str)
    def _family_selected(self, texture: str, representative: str) -> None:
        index = self.texture_combo.findData(texture)
        if index >= 0:
            self.texture_combo.setCurrentIndex(index)
            self.flop_input.clear()
            self.status_label.setText(
                f"{friendly_texture(texture)} kategorisi seçildi. Analiz yenileniyor…"
            )
            self.run_search()
            return

        self.flop_input.setText(representative)
        self.status_label.setText(
            f"{representative} temsilî board olarak seçildi. Analiz yenileniyor…"
        )
        self.run_search()

    def _update_cards(
        self,
        summary: dict[str, Any],
    ) -> None:
        self.hands_card.value_label.setText(
            f"{int(summary.get('hands', 0)):,}"
            .replace(",", ".")
        )
        self.flop_bet_card.value_label.setText(
            f"{float(summary.get('flop_bet', 0.0)):.2f}%"
        )
        self.turn_bet_card.value_label.setText(
            f"{float(summary.get('turn_bet', 0.0)):.2f}%"
        )
        self.river_bet_card.value_label.setText(
            f"{float(summary.get('river_bet', 0.0)):.2f}%"
        )
        self.fold_card.value_label.setText(
            f"{float(summary.get('fold', 0.0)):.2f}%"
        )
        self.avg_pot_card.value_label.setText(
            f"{float(summary.get('avg_pot', 0.0)):.2f}"
        )

    def _fill_table(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(rows))

        keys = [
            "hand_id",
            "site",
            "stakes",
            "table_name",
            "played_at",
            "flop",
            "texture",
            "turn",
            "river",
            "pot",
            "rake",
            "source_file",
        ]

        for row_index, row in enumerate(rows):
            for column_index, key in enumerate(keys):
                value = row.get(key)

                item = QTableWidgetItem(
                    ""
                    if value is None
                    else str(value)
                )

                if column_index in (0, 9, 10):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )

                self.table.setItem(
                    row_index,
                    column_index,
                    item,
                )

        self.table.setSortingEnabled(True)
        self.table.setUpdatesEnabled(True)

    def clear_filters(self) -> None:
        if self.search_thread is not None:
            return

        self.mode_combo.setCurrentIndex(0)
        self.entity_combo.clear()
        self.site_combo.setCurrentIndex(0)
        self.stakes_combo.setCurrentIndex(0)
        self.texture_combo.setCurrentIndex(0)

        self.flop_input.clear()
        self.turn_input.clear()
        self.river_input.clear()

        self.compare_label.hide()

        self._update_cards(
            {
                "hands": 0,
                "flop_bet": 0.0,
                "turn_bet": 0.0,
                "river_bet": 0.0,
                "fold": 0.0,
                "avg_pot": 0.0,
            }
        )

        self._update_family_cards([])
        self.table.clearContents()
        self.table.setRowCount(0)
        self.status_label.setText(
            "Filtreler temizlendi."
        )
