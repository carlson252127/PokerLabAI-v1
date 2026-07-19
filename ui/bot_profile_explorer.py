from __future__ import annotations

from typing import Any

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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.bot_profile_service import BotProfileService


class BotProfileWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        database_path: str,
        mode: str,
        entity_name: str,
        site: str,
        stakes: str,
        minimum_hands: int,
    ) -> None:
        super().__init__()
        self.service = BotProfileService(database_path)
        self.args = {
            "mode": mode,
            "entity_name": entity_name,
            "site": site,
            "stakes": stakes,
            "minimum_hands": minimum_hands,
        }

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(
                self.service.build_profile(**self.args)
            )
        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )


class BotProfileExplorer(QWidget):
    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = database_path
        self.service = BotProfileService(database_path)
        self.worker_thread: QThread | None = None
        self.worker: BotProfileWorker | None = None
        self.filters_loaded = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Bot Profile Report")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Oyuncu veya alias profilini pool ile birleştirilmiş "
            "preflop, postflop ve open-size metriklerinde karşılaştır."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName("BotProfileFilters")
        grid = QGridLayout(filters)
        grid.setContentsMargins(16, 16, 16, 16)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Player", "PLAYER")
        self.mode_combo.addItem("Alias Group", "ALIAS")

        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumWidth(240)

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")

        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.minimum_hands = QSpinBox()
        self.minimum_hands.setRange(1, 100_000_000)
        self.minimum_hands.setValue(500)
        self.minimum_hands.setSingleStep(500)

        labels = [
            "Profil Tipi",
            "Oyuncu / Alias",
            "Site",
            "Stakes",
            "Minimum Hand",
        ]
        widgets = [
            self.mode_combo,
            self.entity_combo,
            self.site_combo,
            self.stakes_combo,
            self.minimum_hands,
        ]

        for index, (label, widget) in enumerate(
            zip(labels, widgets)
        ):
            grid.addWidget(QLabel(label), 0, index)
            grid.addWidget(widget, 1, index)

        self.load_button = QPushButton("Profil Listesini Yükle")
        self.report_button = QPushButton("Bot Profilini Oluştur")

        self.load_button.clicked.connect(self.load_entities)
        self.report_button.clicked.connect(self.run_report)

        buttons = QHBoxLayout()
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.report_button)
        buttons.addStretch()

        grid.addLayout(buttons, 2, 0, 1, 5)
        root.addWidget(filters)

        cards = QHBoxLayout()
        self.name_card = self._card("Profil", "—")
        self.hands_card = self._card("Hands", "0")
        self.nick_card = self._card("Birleşen Nick", "1")
        self.strongest_card = self._card("En Büyük Fark", "—")

        for card in (
            self.name_card,
            self.hands_card,
            self.nick_card,
            self.strongest_card,
        ):
            cards.addWidget(card)

        root.addLayout(cards)

        self.summary_label = QLabel(
            "Profil seçip raporu oluştur."
        )
        self.summary_label.setObjectName("BotProfileSummary")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                "Metrik",
                "Bot/Oyuncu",
                "Pool",
                "Delta",
                "Yorum",
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
        for index in range(4):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        header.setSectionResizeMode(
            4,
            QHeaderView.ResizeMode.Stretch,
        )

        root.addWidget(self.table, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)

        note = QLabel(
            "Open WWSF/W$SD yalnızca first-raise/open yapılan elleri kapsar. "
            "Genel WWSF/W$SD motoru sonraki aşamada tüm pot tipleri için eklenecek."
        )
        note.setObjectName("PageSubtitle")
        note.setWordWrap(True)
        root.addWidget(note)

        self.setStyleSheet(
            """
            QFrame#BotProfileFilters {
                background:#171b24;
                border:1px solid #303744;
                border-radius:12px;
            }

            QFrame#BotProfileCard {
                background:#1d222d;
                border:1px solid #343b49;
                border-radius:11px;
            }

            QLabel#BotProfileCardTitle {
                color:#9ca3af;
                font-size:12px;
            }

            QLabel#BotProfileCardValue {
                font-size:21px;
                font-weight:800;
            }

            QLabel#BotProfileSummary {
                padding:14px;
                background:#23262d;
                border:1px solid #3b4658;
                border-radius:10px;
                font-size:14px;
                font-weight:700;
            }
            """
        )

    def _card(
        self,
        title: str,
        value: str,
    ) -> QFrame:
        frame = QFrame()
        frame.setObjectName("BotProfileCard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 11, 15, 11)

        title_label = QLabel(title)
        title_label.setObjectName("BotProfileCardTitle")

        value_label = QLabel(value)
        value_label.setObjectName("BotProfileCardValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        frame.value_label = value_label
        layout.addWidget(title_label)
        layout.addWidget(value_label)

        return frame

    def refresh_filters(self) -> None:
        if self.filters_loaded:
            return

        try:
            with self.service.player_service.connect() as con:
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
                self.site_combo.addItem(str(row[0]), str(row[0]))

            for row in stakes:
                self.stakes_combo.addItem(str(row[0]), str(row[0]))

            self.filters_loaded = True

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Bot Profile Filtre Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def load_entities(self) -> None:
        try:
            rows = self.service.available_entities(
                mode=str(self.mode_combo.currentData()),
                site=str(self.site_combo.currentData() or ""),
                stakes=str(self.stakes_combo.currentData() or ""),
                minimum_hands=self.minimum_hands.value(),
            )

            self.entity_combo.clear()

            for row in rows:
                self.entity_combo.addItem(
                    f"{row['player_name']} "
                    f"({int(row['hands']):,} hands)",
                    row["player_name"],
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

    def run_report(self) -> None:
        if self.worker_thread is not None:
            return

        entity_name = str(
            self.entity_combo.currentData() or ""
        )

        if not entity_name:
            QMessageBox.information(
                self,
                "Bot Profile",
                "Önce profil listesini yükleyip seçim yap.",
            )
            return

        self.load_button.setEnabled(False)
        self.report_button.setEnabled(False)
        self.status_label.setText("Bot profili hesaplanıyor…")

        self.worker_thread = QThread(self)
        self.worker = BotProfileWorker(
            database_path=self.database_path,
            mode=str(self.mode_combo.currentData()),
            entity_name=entity_name,
            site=str(self.site_combo.currentData() or ""),
            stakes=str(self.stakes_combo.currentData() or ""),
            minimum_hands=self.minimum_hands.value(),
        )

        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._report_finished)
        self.worker.failed.connect(self._report_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    @Slot(dict)
    def _report_finished(
        self,
        report: dict[str, Any],
    ) -> None:
        metrics = report.get("metrics", [])

        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(metrics))

        for row_index, row in enumerate(metrics):
            suffix = "x" if row["key"] == "avg_size_bb" else "%"

            values = [
                row["label"],
                f"{float(row['entity']):.2f}{suffix}",
                f"{float(row['pool']):.2f}{suffix}",
                f"{float(row['delta']):+.2f}{suffix}",
                row["interpretation"],
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))

                if 1 <= column_index <= 3:
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

        self.name_card.value_label.setText(
            report["entity_name"]
        )
        self.hands_card.value_label.setText(
            f"{int(report['hands']):,}".replace(",", ".")
        )
        self.nick_card.value_label.setText(
            str(report["merged_nicks"])
        )

        strongest = report.get("strongest")

        if strongest:
            self.strongest_card.value_label.setText(
                f"{strongest['label']} "
                f"{float(strongest['delta']):+.2f}"
            )
        else:
            self.strongest_card.value_label.setText("—")

        self.summary_label.setText(report["summary"])
        self.status_label.setText(
            f"{len(metrics)} metrik pool ile karşılaştırıldı."
        )

    @Slot(str)
    def _report_failed(
        self,
        message: str,
    ) -> None:
        QMessageBox.critical(
            self,
            "Bot Profile Hatası",
            message,
        )
        self.status_label.setText("Profil oluşturulamadı.")

    def _cleanup_worker(self) -> None:
        self.load_button.setEnabled(True)
        self.report_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
