from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class PopulationWorker(QObject):
    finished = Signal(dict, list)
    failed = Signal(str)

    def __init__(
        self,
        database_path: str,
        site: str,
        stakes: str,
    ) -> None:
        super().__init__()
        self.database_path = database_path
        self.site = site
        self.stakes = stakes

    @Slot()
    def run(self) -> None:
        try:
            where_parts: list[str] = []
            params: list[str] = []

            if self.site:
                where_parts.append("site = ?")
                params.append(self.site)

            if self.stakes:
                where_parts.append("stakes = ?")
                params.append(self.stakes)

            where_sql = ""
            if where_parts:
                where_sql = "WHERE " + " AND ".join(where_parts)

            with duckdb.connect(
                self.database_path,
                read_only=True,
            ) as con:
                summary = con.execute(
                    f"""
                    SELECT
                        COUNT(*) AS hands,
                        COUNT(DISTINCT table_name) AS tables,
                        AVG(pot) AS avg_pot,
                        AVG(rake) AS avg_rake,
                        SUM(CASE WHEN flop IS NOT NULL
                                 AND flop <> '' THEN 1 ELSE 0 END)
                            AS flop_hands
                    FROM hands
                    {where_sql}
                    """,
                    params,
                ).fetchone()

                board_rows = con.execute(
                    f"""
                    SELECT
                        flop,
                        COUNT(*) AS hands,
                        AVG(pot) AS avg_pot,
                        AVG(rake) AS avg_rake
                    FROM hands
                    {where_sql}
                    GROUP BY flop
                    HAVING flop IS NOT NULL
                       AND flop <> ''
                    ORDER BY hands DESC
                    LIMIT 5000
                    """,
                    params,
                ).fetchall()

            texture_map: dict[str, dict[str, float]] = {}

            for flop, hand_count, avg_pot, avg_rake in board_rows:
                texture = self._classify_flop(flop)

                if texture not in texture_map:
                    texture_map[texture] = {
                        "hands": 0,
                        "weighted_pot": 0.0,
                        "weighted_rake": 0.0,
                    }

                count = int(hand_count or 0)
                texture_map[texture]["hands"] += count
                texture_map[texture]["weighted_pot"] += (
                    float(avg_pot or 0.0) * count
                )
                texture_map[texture]["weighted_rake"] += (
                    float(avg_rake or 0.0) * count
                )

            textures: list[dict[str, Any]] = []

            for texture, values in texture_map.items():
                count = int(values["hands"])

                textures.append(
                    {
                        "texture": texture,
                        "hands": count,
                        "avg_pot": (
                            values["weighted_pot"] / count
                            if count else 0.0
                        ),
                        "avg_rake": (
                            values["weighted_rake"] / count
                            if count else 0.0
                        ),
                    }
                )

            textures.sort(
                key=lambda row: row["hands"],
                reverse=True,
            )

            result = {
                "hands": int(summary[0] or 0),
                "tables": int(summary[1] or 0),
                "avg_pot": float(summary[2] or 0.0),
                "avg_rake": float(summary[3] or 0.0),
                "flop_hands": int(summary[4] or 0),
            }

            self.finished.emit(result, textures)

        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )

    def _classify_flop(self, flop: str | None) -> str:
        cards = re.findall(
            r"([2-9TJQKA])([shdcSHDC])",
            str(flop or ""),
        )

        if len(cards) < 3:
            return "Bilinmiyor"

        ranks = [rank.upper() for rank, _ in cards[:3]]
        suits = [suit.lower() for _, suit in cards[:3]]

        labels: list[str] = []

        unique_ranks = len(set(ranks))
        unique_suits = len(set(suits))

        if unique_ranks == 1:
            labels.append("Trips")
        elif unique_ranks == 2:
            labels.append("Paired")
        else:
            labels.append("Unpaired")

        if unique_suits == 1:
            labels.append("Monotone")
        elif unique_suits == 2:
            labels.append("Two-Tone")
        else:
            labels.append("Rainbow")

        if "A" in ranks:
            labels.append("A-High")
        elif "K" in ranks:
            labels.append("K-High")
        elif "Q" in ranks:
            labels.append("Q-High")
        else:
            labels.append("Low/Mid")

        rank_map = {
            "2": 2, "3": 3, "4": 4, "5": 5,
            "6": 6, "7": 7, "8": 8, "9": 9,
            "T": 10, "J": 11, "Q": 12,
            "K": 13, "A": 14,
        }

        values = sorted(
            rank_map[rank]
            for rank in set(ranks)
        )

        if len(values) == 3:
            gaps = [
                values[index + 1] - values[index]
                for index in range(2)
            ]
            labels.append(
                "Connected"
                if max(gaps) <= 2
                else "Disconnected"
            )

        return " / ".join(labels)


class PopulationExplorer(QWidget):
    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = str(Path(database_path))
        self.worker_thread: QThread | None = None
        self.worker: PopulationWorker | None = None
        self.filters_loaded = False

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Population Explorer")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Site, limit ve board texture bazında havuz dağılımı."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filter_frame = QFrame()
        filter_frame.setObjectName("PopulationFilters")

        filter_layout = QGridLayout(filter_frame)
        filter_layout.setContentsMargins(16, 16, 16, 16)
        filter_layout.setHorizontalSpacing(12)

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")

        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.analyze_button = QPushButton("Analiz Et")
        self.analyze_button.clicked.connect(self.refresh_analysis)

        filter_layout.addWidget(QLabel("Site"), 0, 0)
        filter_layout.addWidget(QLabel("Stakes"), 0, 1)
        filter_layout.addWidget(self.site_combo, 1, 0)
        filter_layout.addWidget(self.stakes_combo, 1, 1)
        filter_layout.addWidget(self.analyze_button, 1, 2)

        root.addWidget(filter_frame)

        cards = QHBoxLayout()
        cards.setSpacing(12)

        self.hands_card = self._card("Toplam Hand", "0")
        self.tables_card = self._card("Masa", "0")
        self.flop_card = self._card("Flop Görülen", "0")
        self.pot_card = self._card("Ort. Pot", "0")
        self.rake_card = self._card("Ort. Rake", "0")

        for card in (
            self.hands_card,
            self.tables_card,
            self.flop_card,
            self.pot_card,
            self.rake_card,
        ):
            cards.addWidget(card)

        root.addLayout(cards)

        self.status_label = QLabel(
            "Population analizi için Analiz Et düğmesine bas."
        )
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                "Board Texture",
                "Hand",
                "Dağılım %",
                "Ort. Pot",
                "Ort. Rake",
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

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        for index in range(1, 5):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        root.addWidget(self.table, 1)

        self.setStyleSheet(
            """
            QFrame#PopulationFilters {
                background: #171b24;
                border: 1px solid #303744;
                border-radius: 12px;
            }

            QFrame#PopulationCard {
                background: #1d222d;
                border: 1px solid #343b49;
                border-radius: 11px;
            }

            QLabel#PopulationCardTitle {
                color: #9ca3af;
                font-size: 12px;
                font-weight: 600;
            }

            QLabel#PopulationCardValue {
                font-size: 22px;
                font-weight: 800;
            }
            """
        )

    def _card(self, title: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("PopulationCard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)

        title_label = QLabel(title)
        title_label.setObjectName("PopulationCardTitle")

        value_label = QLabel(value)
        value_label.setObjectName("PopulationCardValue")

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
                    WHERE site IS NOT NULL AND site <> ''
                    ORDER BY site
                    """
                ).fetchall()

                stakes = con.execute(
                    """
                    SELECT DISTINCT stakes
                    FROM hands
                    WHERE stakes IS NOT NULL AND stakes <> ''
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
                f"Filtre hatası: {type(exc).__name__}: {exc}"
            )

    def refresh_analysis(self) -> None:
        if self.worker_thread is not None:
            return

        self.analyze_button.setEnabled(False)
        self.status_label.setText("Population hesaplanıyor…")

        self.worker_thread = QThread(self)
        self.worker = PopulationWorker(
            database_path=self.database_path,
            site=str(self.site_combo.currentData() or ""),
            stakes=str(self.stakes_combo.currentData() or ""),
        )

        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._analysis_finished)
        self.worker.failed.connect(self._analysis_failed)

        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)

        self.worker_thread.start()

    @Slot(dict, list)
    def _analysis_finished(
        self,
        summary: dict,
        textures: list,
    ) -> None:
        hands = int(summary.get("hands", 0))
        flop_hands = int(summary.get("flop_hands", 0))

        self.hands_card.value_label.setText(
            f"{hands:,}".replace(",", ".")
        )
        self.tables_card.value_label.setText(
            f"{int(summary.get('tables', 0)):,}".replace(",", ".")
        )
        self.flop_card.value_label.setText(
            f"{flop_hands:,}".replace(",", ".")
        )
        self.pot_card.value_label.setText(
            f"{float(summary.get('avg_pot', 0.0)):.2f}"
        )
        self.rake_card.value_label.setText(
            f"{float(summary.get('avg_rake', 0.0)):.3f}"
        )

        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(textures))

        for row_index, row in enumerate(textures):
            count = int(row["hands"])
            percentage = (
                count / flop_hands * 100
                if flop_hands else 0.0
            )

            values = [
                row["texture"],
                f"{count:,}".replace(",", "."),
                f"{percentage:.2f}",
                f"{float(row['avg_pot']):.2f}",
                f"{float(row['avg_rake']):.3f}",
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

        self.status_label.setText(
            f"{len(textures)} texture grubu hesaplandı."
        )

    @Slot(str)
    def _analysis_failed(self, message: str) -> None:
        QMessageBox.critical(
            self,
            "Population Hatası",
            message,
        )
        self.status_label.setText("Analiz başarısız.")

    def _cleanup_worker(self) -> None:
        self.analyze_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
