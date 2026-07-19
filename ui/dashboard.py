from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class DashboardWorker(QThread):
    loaded = Signal(dict)
    failed = Signal(str)

    def __init__(self, database_path: str) -> None:
        super().__init__()
        self.database_path = database_path

    def run(self) -> None:
        try:
            self.loaded.emit(self._load_metrics())
        except Exception as exc:
            self.failed.emit(str(exc))

    def _table_exists(
        self,
        con: duckdb.DuckDBPyConnection,
        table_name: str,
    ) -> bool:
        row = con.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE LOWER(table_name) = LOWER(?)
            """,
            [table_name],
        ).fetchone()
        return bool(row and int(row[0] or 0) > 0)

    def _load_metrics(self) -> dict[str, Any]:
        db_path = Path(self.database_path)
        if not db_path.exists():
            return {
                "database_ready": False,
                "database_size": "0 MB",
                "total_hands": 0,
                "total_players": 0,
                "bot_players": 0,
                "human_players": 0,
                "top_site": "—",
                "top_stakes": "—",
                "last_hand": "—",
            }

        with duckdb.connect(str(db_path), read_only=True) as con:
            con.execute("PRAGMA threads=4")

            total_hands = 0
            total_players = 0
            bot_players = 0
            top_site = "—"
            top_stakes = "—"
            last_hand = "—"

            if self._table_exists(con, "hands"):
                total_hands = int(
                    con.execute("SELECT COUNT(*) FROM hands").fetchone()[0] or 0
                )

                row = con.execute("""
                    SELECT COALESCE(NULLIF(TRIM(site), ''), 'Unknown'), COUNT(*)
                    FROM hands
                    GROUP BY 1
                    ORDER BY 2 DESC
                    LIMIT 1
                """).fetchone()
                if row:
                    top_site = str(row[0])

                row = con.execute("""
                    SELECT COALESCE(NULLIF(TRIM(stakes), ''), 'Unknown'), COUNT(*)
                    FROM hands
                    GROUP BY 1
                    ORDER BY 2 DESC
                    LIMIT 1
                """).fetchone()
                if row:
                    top_stakes = str(row[0])

                columns = {
                    str(row[0]).lower()
                    for row in con.execute("""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE LOWER(table_name) = 'hands'
                    """).fetchall()
                }
                for candidate in (
                    "played_at",
                    "hand_time",
                    "started_at",
                    "created_at",
                    "imported_at",
                ):
                    if candidate in columns:
                        row = con.execute(
                            f"SELECT MAX({candidate}) FROM hands"
                        ).fetchone()
                        if row and row[0] is not None:
                            value = row[0]
                            if isinstance(value, datetime):
                                last_hand = value.strftime("%d.%m.%Y %H:%M")
                            else:
                                last_hand = str(value)
                        break

            if self._table_exists(con, "hand_players"):
                total_players = int(
                    con.execute("""
                        SELECT COUNT(DISTINCT LOWER(TRIM(player_name)))
                        FROM hand_players
                        WHERE player_name IS NOT NULL
                          AND TRIM(player_name) <> ''
                    """).fetchone()[0] or 0
                )

            if self._table_exists(con, "bot_group_members"):
                bot_players = int(
                    con.execute("""
                        SELECT COUNT(DISTINCT LOWER(TRIM(player_name)))
                        FROM bot_group_members
                        WHERE player_name IS NOT NULL
                          AND TRIM(player_name) <> ''
                    """).fetchone()[0] or 0
                )

        database_size_mb = db_path.stat().st_size / (1024 * 1024)
        if database_size_mb >= 1024:
            database_size = f"{database_size_mb / 1024:.2f} GB"
        else:
            database_size = f"{database_size_mb:.1f} MB"

        return {
            "database_ready": True,
            "database_size": database_size,
            "total_hands": total_hands,
            "total_players": total_players,
            "bot_players": bot_players,
            "human_players": max(0, total_players - bot_players),
            "top_site": top_site,
            "top_stakes": top_stakes,
            "last_hand": last_hand,
        }


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "—") -> None:
        super().__init__()
        self.setObjectName("metricCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")

        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")

        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: Any) -> None:
        self.value_label.setText(str(value))


class DashboardPage(QWidget):
    def __init__(
        self,
        database_path: str = "database/pokerlab.duckdb",
    ) -> None:
        super().__init__()

        self.database_path = database_path
        self.worker: DashboardWorker | None = None
        self.cards: dict[str, MetricCard] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(18)

        header = QHBoxLayout()

        title_box = QVBoxLayout()
        title = QLabel("PokerLab AI")
        title.setObjectName("dashboardTitle")

        subtitle = QLabel(
            "Canlı veritabanı özeti ve araştırma durumu"
        )
        subtitle.setObjectName("dashboardSubtitle")

        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        self.refresh_button = QPushButton("Yenile")
        self.refresh_button.clicked.connect(self.refresh)

        header.addLayout(title_box)
        header.addStretch()
        header.addWidget(self.refresh_button)

        root.addLayout(header)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        card_specs = [
            ("total_hands", "Toplam Hand"),
            ("total_players", "Toplam Oyuncu"),
            ("bot_players", "Bot Oyuncu"),
            ("human_players", "Human Oyuncu"),
            ("top_site", "En Aktif Site"),
            ("top_stakes", "En Aktif Limit"),
            ("database_size", "Veritabanı Boyutu"),
            ("last_hand", "Son Hand / Import"),
        ]

        for index, (key, label) in enumerate(card_specs):
            card = MetricCard(label)
            self.cards[key] = card
            grid.addWidget(card, index // 4, index % 4)

        root.addLayout(grid)

        self.status_label = QLabel("Dashboard hazırlanıyor...")
        self.status_label.setObjectName("dashboardStatus")
        root.addWidget(self.status_label)
        root.addStretch()

        self.setStyleSheet("""
            QWidget {
                background: #313338;
                color: #f2f3f5;
            }

            QLabel#dashboardTitle {
                font-size: 30px;
                font-weight: 700;
            }

            QLabel#dashboardSubtitle {
                color: #b5bac1;
                font-size: 14px;
            }

            QFrame#metricCard {
                background: #2b2d31;
                border: 1px solid #3f4147;
                border-radius: 12px;
                min-height: 96px;
            }

            QLabel#metricTitle {
                color: #b5bac1;
                font-size: 13px;
            }

            QLabel#metricValue {
                color: white;
                font-size: 23px;
                font-weight: 700;
            }

            QLabel#dashboardStatus {
                color: #b5bac1;
                font-size: 13px;
            }

            QPushButton {
                background: #5865f2;
                color: white;
                border: none;
                border-radius: 7px;
                padding: 9px 18px;
                font-weight: 600;
            }

            QPushButton:hover {
                background: #4752c4;
            }

            QPushButton:disabled {
                background: #4e5058;
                color: #949ba4;
            }
        """)

        self.refresh()

    @staticmethod
    def _format_number(value: int) -> str:
        return f"{int(value or 0):,}".replace(",", ".")

    def refresh(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return

        self.refresh_button.setEnabled(False)
        self.status_label.setText("Veritabanı metrikleri hesaplanıyor...")

        self.worker = DashboardWorker(self.database_path)
        self.worker.loaded.connect(self._metrics_loaded)
        self.worker.failed.connect(self._metrics_failed)
        self.worker.finished.connect(
            lambda: self.refresh_button.setEnabled(True)
        )
        self.worker.start()

    def _metrics_loaded(self, metrics: dict[str, Any]) -> None:
        numeric_keys = {
            "total_hands",
            "total_players",
            "bot_players",
            "human_players",
        }

        for key, card in self.cards.items():
            value = metrics.get(key, "—")
            if key in numeric_keys:
                value = self._format_number(int(value or 0))
            card.set_value(value)

        if metrics.get("database_ready"):
            self.status_label.setText(
                "DuckDB hazır • Canlı veriler başarıyla yüklendi."
            )
        else:
            self.status_label.setText(
                "Veritabanı bulunamadı. İlk import sonrasında kartlar dolacak."
            )

    def _metrics_failed(self, message: str) -> None:
        self.status_label.setText(
            f"Dashboard verileri yüklenemedi: {message}"
        )
