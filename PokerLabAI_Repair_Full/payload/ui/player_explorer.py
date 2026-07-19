from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.player_stats_service import PlayerStatsService


class PlayerStatsWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        database_path: str,
        site: str,
        stakes: str,
        name_query: str,
        minimum_hands: int,
        use_aliases: bool,
    ) -> None:
        super().__init__()

        self.service = PlayerStatsService(database_path)
        self.site = site
        self.stakes = stakes
        self.name_query = name_query
        self.minimum_hands = minimum_hands
        self.use_aliases = use_aliases

    @Slot()
    def run(self) -> None:
        try:
            rows = self.service.get_players(
                site=self.site,
                stakes=self.stakes,
                name_query=self.name_query,
                minimum_hands=self.minimum_hands,
                limit=500,
                use_aliases=self.use_aliases,
            )
            self.finished.emit(rows)

        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )


class PlayerExplorer(QWidget):
    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = database_path
        self.service = PlayerStatsService(database_path)

        self.worker_thread: QThread | None = None
        self.worker: PlayerStatsWorker | None = None
        self.filters_loaded = False

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Player Explorer")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Oyuncu bazında VPIP, PFR, 3Bet ve barrel statları."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filter_frame = QFrame()
        filter_frame.setObjectName("PlayerFilters")

        grid = QGridLayout(filter_frame)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")

        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(
            "Oyuncu adı ara..."
        )

        self.minimum_hands = QSpinBox()
        self.minimum_hands.setRange(1, 100000000)
        self.minimum_hands.setValue(100)
        self.minimum_hands.setSingleStep(100)

        self.use_aliases_checkbox = QCheckBox(
            "Alias gruplarını birleştir"
        )
        self.use_aliases_checkbox.setChecked(True)

        self.search_button = QPushButton("Oyuncuları Hesapla")
        self.search_button.clicked.connect(self.refresh_players)
        self.name_input.returnPressed.connect(self.refresh_players)

        labels = [
            "Site",
            "Stakes",
            "Oyuncu",
            "Minimum Hand",
        ]

        widgets = [
            self.site_combo,
            self.stakes_combo,
            self.name_input,
            self.minimum_hands,
        ]

        for index, (label, widget) in enumerate(
            zip(labels, widgets)
        ):
            grid.addWidget(QLabel(label), 0, index)
            grid.addWidget(widget, 1, index)

        grid.addWidget(self.use_aliases_checkbox, 1, 4)
        grid.addWidget(self.search_button, 1, 5)
        root.addWidget(filter_frame)

        cards = QHBoxLayout()
        cards.setSpacing(12)

        self.player_count_card = self._card(
            "Gösterilen Oyuncu",
            "0",
        )
        self.hand_count_card = self._card(
            "Toplam Sample",
            "0",
        )
        self.top_player_card = self._card(
            "En Çok Hand",
            "—",
        )

        cards.addWidget(self.player_count_card)
        cards.addWidget(self.hand_count_card)
        cards.addWidget(self.top_player_card)
        cards.addStretch()

        root.addLayout(cards)

        self.status_label = QLabel(
            "Filtreleri seçip oyuncuları hesapla."
        )
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels(
            [
                "Oyuncu",
                "Hands",
                "Birleşen Nick",
                "VPIP",
                "PFR",
                "3Bet",
                "Flop CBet",
                "F CBet Sample",
                "Turn Barrel",
                "T Barrel Sample",
                "River Barrel",
                "R Barrel Sample",
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
            QHeaderView.ResizeMode.Stretch,
        )

        for index in range(1, 12):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        root.addWidget(self.table, 1)

        self.setStyleSheet(
            """
            QFrame#PlayerFilters {
                background: #171b24;
                border: 1px solid #303744;
                border-radius: 12px;
            }

            QFrame#PlayerCard {
                background: #1d222d;
                border: 1px solid #343b49;
                border-radius: 11px;
            }

            QLabel#PlayerCardTitle {
                color: #9ca3af;
                font-size: 12px;
            }

            QLabel#PlayerCardValue {
                font-size: 22px;
                font-weight: 800;
            }
            """
        )

    def _card(self, title: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("PlayerCard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)

        title_label = QLabel(title)
        title_label.setObjectName("PlayerCardTitle")

        value_label = QLabel(value)
        value_label.setObjectName("PlayerCardValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        frame.value_label = value_label

        layout.addWidget(title_label)
        layout.addWidget(value_label)

        return frame

    def refresh_filters(self) -> None:
        if self.filters_loaded:
            return

        try:
            with self.service.connect() as con:
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
            QMessageBox.critical(
                self,
                "Player Filtre Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def refresh_players(self) -> None:
        if self.worker_thread is not None:
            return

        self.search_button.setEnabled(False)
        self.status_label.setText(
            "Oyuncu statları hesaplanıyor…"
        )

        self.worker_thread = QThread(self)
        self.worker = PlayerStatsWorker(
            database_path=self.database_path,
            site=str(self.site_combo.currentData() or ""),
            stakes=str(self.stakes_combo.currentData() or ""),
            name_query=self.name_input.text().strip(),
            minimum_hands=self.minimum_hands.value(),
            use_aliases=self.use_aliases_checkbox.isChecked(),
        )

        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._players_finished)
        self.worker.failed.connect(self._players_failed)

        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)

        self.worker_thread.start()

    @Slot(list)
    def _players_finished(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(rows))

        total_hands = 0

        for row_index, row in enumerate(rows):
            total_hands += int(row["hands"])

            values = [
                row["player_name"],
                str(row["hands"]),
                str(row.get("merged_nicks", 1)),
                f"{row['vpip']:.2f}",
                f"{row['pfr']:.2f}",
                f"{row['three_bet']:.2f}",
                self._stat_text(row["flop_cbet"]),
                (
                    f"{row['flop_cbet_made']}/"
                    f"{row['flop_cbet_opp']}"
                ),
                self._stat_text(row["turn_barrel"]),
                (
                    f"{row['turn_barrel_made']}/"
                    f"{row['turn_barrel_opp']}"
                ),
                self._stat_text(row["river_barrel"]),
                (
                    f"{row['river_barrel_made']}/"
                    f"{row['river_barrel_opp']}"
                ),
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))

                if column_index > 0:
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

        self.player_count_card.value_label.setText(
            f"{len(rows):,}".replace(",", ".")
        )
        self.hand_count_card.value_label.setText(
            f"{total_hands:,}".replace(",", ".")
        )
        self.top_player_card.value_label.setText(
            rows[0]["player_name"] if rows else "—"
        )

        self.status_label.setText(
            f"{len(rows)} oyuncu gösteriliyor."
        )

    def _stat_text(
        self,
        value: float | None,
    ) -> str:
        if value is None:
            return "—"
        return f"{value:.2f}"

    @Slot(str)
    def _players_failed(self, message: str) -> None:
        QMessageBox.critical(
            self,
            "Player Explorer Hatası",
            message,
        )
        self.status_label.setText(
            "Oyuncu statları hesaplanamadı."
        )

    def _cleanup_worker(self) -> None:
        self.search_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
