from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from services.adaptation_monitor_service import AdaptationMonitorService


class AdaptationWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, database_path: str, **kwargs: Any) -> None:
        super().__init__()
        self.service = AdaptationMonitorService(database_path)
        self.kwargs = kwargs

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.service.analyze(**self.kwargs))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class AdaptationMonitorExplorer(QWidget):
    COLUMNS = [
        ("block_label", "5K Blok"),
        ("opens", "Open"),
        ("pf_fold", "PF Fold"),
        ("delta_pf_fold", "Δ PF Fold"),
        ("pf_call", "PF Call"),
        ("pf_3bet", "PF 3Bet"),
        ("delta_pf_3bet", "Δ PF 3Bet"),
        ("flop_fold", "Flop Fold"),
        ("delta_flop_fold", "Δ Flop"),
        ("flop_sample", "Flop Smp"),
        ("turn_fold", "Turn Fold"),
        ("delta_turn_fold", "Δ Turn"),
        ("turn_sample", "Turn Smp"),
        ("river_fold", "River Fold"),
        ("delta_river_fold", "Δ River"),
        ("river_sample", "River Smp"),
        ("confidence", "Güven"),
    ]

    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database_path = database_path
        self.service = AdaptationMonitorService(database_path)
        self.worker_thread: QThread | None = None
        self.worker: AdaptationWorker | None = None

        self._build_ui()
        QTimer.singleShot(100, self.refresh_filters)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(13)

        title = QLabel("Adaptation Monitor v1")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Poolun seçilen oyuncu/alias ve open-size branch'ine "
            "5.000 el bloklarında adapte olup olmadığını ölçer."
        )
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        frame = QFrame()
        frame.setObjectName("AdaptationFilters")
        grid = QGridLayout(frame)
        grid.setContentsMargins(15, 15, 15, 15)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Player", "PLAYER")
        self.mode_combo.addItem("Alias Group", "ALIAS")

        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumWidth(240)

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")

        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.position_combo = QComboBox()
        for label, value in [
            ("Tüm Pozisyonlar", ""), ("UTG", "UTG"), ("UTG+1", "UTG+1"),
            ("HJ", "HJ"), ("CO", "CO"), ("BTN", "BTN"),
            ("SB", "SB"), ("BB", "BB"),
        ]:
            self.position_combo.addItem(label, value)

        self.size_combo = QComboBox()
        for label, value in [
            ("Tüm Sizelar", ""), ("≤2.0x", "≤2.0x"),
            ("2.1–2.3x", "2.1–2.3x"), ("2.4–2.6x", "2.4–2.6x"),
            ("2.7–3.1x", "2.7–3.1x"), (">3.1x", ">3.1x"),
        ]:
            self.size_combo.addItem(label, value)

        self.block_size = QComboBox()
        for value in (2500, 5000, 10000, 20000):
            self.block_size.addItem(f"{value:,}".replace(",", "."), value)
        self.block_size.setCurrentIndex(1)

        labels = [
            "Mod", "Oyuncu / Alias", "Site", "Stakes",
            "Pozisyon", "Open Size", "Blok",
        ]
        widgets = [
            self.mode_combo, self.entity_combo, self.site_combo,
            self.stakes_combo, self.position_combo, self.size_combo,
            self.block_size,
        ]

        for index, (label, widget) in enumerate(zip(labels, widgets)):
            grid.addWidget(QLabel(label), 0, index)
            grid.addWidget(widget, 1, index)

        self.load_button = QPushButton("Oyuncu/Alias Yükle")
        self.analyze_button = QPushButton("Adaptasyonu Analiz Et")
        self.load_button.clicked.connect(self.load_entities)
        self.analyze_button.clicked.connect(self.run_analysis)

        buttons = QHBoxLayout()
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.analyze_button)
        buttons.addStretch()
        grid.addLayout(buttons, 2, 0, 1, 7)
        root.addWidget(frame)

        cards = QHBoxLayout()
        self.blocks_card = self._card("Blok", "0")
        self.opens_card = self._card("Open", "0")
        self.score_card = self._card("Adaptation Score", "0")
        self.fold_card = self._card("PF Fold Trend", "+0.0")
        self.threebet_card = self._card("PF 3Bet Trend", "+0.0")
        self.status_card = self._card("Status", "—")
        for card in (
            self.blocks_card, self.opens_card, self.score_card,
            self.fold_card, self.threebet_card, self.status_card,
        ):
            cards.addWidget(card)
        root.addLayout(cards)

        self.summary_label = QLabel("Profil seçip analizi başlat.")
        self.summary_label.setObjectName("AdaptationSummary")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(
            [label for _key, label in self.COLUMNS]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for index in range(len(self.COLUMNS)):
            header.setSectionResizeMode(
                index, QHeaderView.ResizeMode.ResizeToContents
            )
        root.addWidget(self.table, 1)

        self.setStyleSheet(
            """
            QFrame#AdaptationFilters {
                background:#171b24; border:1px solid #303744;
                border-radius:12px;
            }
            QFrame#AdaptationCard {
                background:#1d222d; border:1px solid #343b49;
                border-radius:11px;
            }
            QLabel#AdaptationCardTitle { color:#9ca3af; font-size:12px; }
            QLabel#AdaptationCardValue { font-size:20px; font-weight:800; }
            QLabel#AdaptationSummary {
                padding:14px; background:#23262d;
                border:1px solid #3b4658; border-radius:10px;
                font-size:14px; font-weight:700;
            }
            """
        )

    def _card(self, title: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("AdaptationCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 11, 15, 11)
        title_label = QLabel(title)
        title_label.setObjectName("AdaptationCardTitle")
        value_label = QLabel(value)
        value_label.setObjectName("AdaptationCardValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame.value_label = value_label
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return frame

    def refresh_filters(self) -> None:
        try:
            with self.service.connect() as con:
                sites = con.execute(
                    "SELECT DISTINCT TRIM(site) FROM hands "
                    "WHERE site IS NOT NULL AND TRIM(site)<>'' ORDER BY 1"
                ).fetchall()
                stakes = con.execute(
                    "SELECT DISTINCT TRIM(stakes) FROM hands "
                    "WHERE stakes IS NOT NULL AND TRIM(stakes)<>'' ORDER BY 1"
                ).fetchall()

            self.site_combo.clear()
            self.site_combo.addItem("Tüm Siteler", "")
            for row in sites:
                self.site_combo.addItem(str(row[0]), str(row[0]))

            self.stakes_combo.clear()
            self.stakes_combo.addItem("Tüm Limitler", "")
            for row in stakes:
                self.stakes_combo.addItem(str(row[0]), str(row[0]))
        except Exception as exc:
            QMessageBox.critical(
                self, "Filtre Hatası", f"{type(exc).__name__}: {exc}"
            )

    def load_entities(self) -> None:
        try:
            rows = self.service.available_entities(
                mode=str(self.mode_combo.currentData()),
                site=str(self.site_combo.currentData() or ""),
                stakes=str(self.stakes_combo.currentData() or ""),
                minimum_hands=500,
            )
            self.entity_combo.clear()
            for name, hands in rows:
                self.entity_combo.addItem(
                    f"{name} ({hands:,} hands)", name
                )
            self.status_label.setText(f"{len(rows)} profil yüklendi.")
        except Exception as exc:
            QMessageBox.critical(
                self, "Profil Hatası", f"{type(exc).__name__}: {exc}"
            )

    def run_analysis(self) -> None:
        if self.worker_thread is not None:
            return

        entity = str(self.entity_combo.currentData() or "")
        if not entity:
            QMessageBox.information(
                self, "Adaptation Monitor", "Önce profil yükleyip seç."
            )
            return

        self.load_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.status_label.setText("5K blok adaptasyonu hesaplanıyor…")

        self.worker_thread = QThread(self)
        self.worker = AdaptationWorker(
            self.database_path,
            mode=str(self.mode_combo.currentData()),
            entity_name=entity,
            site=str(self.site_combo.currentData() or ""),
            stakes=str(self.stakes_combo.currentData() or ""),
            position=str(self.position_combo.currentData() or ""),
            size_bucket=str(self.size_combo.currentData() or ""),
            block_size=int(self.block_size.currentData()),
            minimum_open_sample=30,
            minimum_postflop_sample=15,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup)
        self.worker_thread.start()

    @Slot(dict)
    def _finished(self, report: dict[str, Any]) -> None:
        blocks = report.get("blocks", [])
        trend = report.get("trend", {})

        self.blocks_card.value_label.setText(str(report.get("total_blocks", 0)))
        self.opens_card.value_label.setText(
            f"{int(report.get('total_opens', 0)):,}".replace(",", ".")
        )
        self.score_card.value_label.setText(
            f"{float(report.get('adaptation_score', 0)):.0f}"
        )
        self.fold_card.value_label.setText(
            f"{float(trend.get('pf_fold', 0)):+.1f}"
        )
        self.threebet_card.value_label.setText(
            f"{float(trend.get('pf_3bet', 0)):+.1f}"
        )
        self.status_card.value_label.setText(str(report.get("status", "—")))
        self.summary_label.setText(str(report.get("summary", "")))

        self.table.clearContents()
        self.table.setRowCount(len(blocks))
        percent_keys = {
            "pf_fold", "delta_pf_fold", "pf_call", "pf_3bet",
            "delta_pf_3bet", "flop_fold", "delta_flop_fold",
            "turn_fold", "delta_turn_fold", "river_fold",
            "delta_river_fold",
        }

        for row_index, row in enumerate(blocks):
            for column_index, (key, _label) in enumerate(self.COLUMNS):
                value = row.get(key, "")
                if key in percent_keys:
                    display = f"{float(value or 0):+.2f}" if key.startswith("delta_") else f"{float(value or 0):.2f}"
                elif key in {"opens", "flop_sample", "turn_sample", "river_sample"}:
                    display = str(int(value or 0))
                else:
                    display = str(value)
                item = QTableWidgetItem(display)
                if key not in {"block_label", "confidence"}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_index, column_index, item)

        self.status_label.setText(f"{len(blocks)} blok analiz edildi.")

    @Slot(str)
    def _failed(self, message: str) -> None:
        QMessageBox.critical(self, "Adaptation Hatası", message)
        self.status_label.setText("Analiz başarısız.")

    def _cleanup(self) -> None:
        self.load_button.setEnabled(True)
        self.analyze_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
