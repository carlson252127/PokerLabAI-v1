from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from services.bot_fingerprint_service_v2 import BotFingerprintService


class FingerprintWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, database_path: str, **kwargs: Any) -> None:
        super().__init__()
        self.service = BotFingerprintService(database_path)
        self.kwargs = kwargs

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.service.analyze(**self.kwargs))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class BotFingerprintExplorerV2(QWidget):
    COLUMNS = [
        ("label", "DNA Boyutu"),
        ("score", "Score"),
        ("value", "Değer"),
        ("note", "Yorum"),
    ]

    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database_path = database_path
        self.service = BotFingerprintService(database_path)
        self.worker_thread: QThread | None = None
        self.worker: FingerprintWorker | None = None

        self._build_ui()
        QTimer.singleShot(100, self.refresh_filters)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(13)

        title = QLabel("Bot Fingerprint Engine v2")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Open Size, Bot Profile, Pool Response, WWSF/W$SD ve "
            "Size×Board sonuçlarını tek strateji DNA raporunda birleştirir."
        )
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        frame = QFrame()
        frame.setObjectName("FingerprintFilters")
        grid = QGridLayout(frame)
        grid.setContentsMargins(15, 15, 15, 15)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Player", "PLAYER")
        self.mode_combo.addItem("Alias Group", "ALIAS")

        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumWidth(260)

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")

        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.minimum_hands = QSpinBox()
        self.minimum_hands.setRange(100, 100_000_000)
        self.minimum_hands.setValue(500)
        self.minimum_hands.setSingleStep(500)

        labels = ["Mod", "Oyuncu / Alias", "Site", "Stakes", "Minimum Hand"]
        widgets = [
            self.mode_combo, self.entity_combo, self.site_combo,
            self.stakes_combo, self.minimum_hands,
        ]
        for index, (label, widget) in enumerate(zip(labels, widgets)):
            grid.addWidget(QLabel(label), 0, index)
            grid.addWidget(widget, 1, index)

        self.load_button = QPushButton("Profil Listesini Yükle")
        self.analyze_button = QPushButton("Fingerprint Üret")
        self.load_button.clicked.connect(self.load_entities)
        self.analyze_button.clicked.connect(self.run_analysis)

        buttons = QHBoxLayout()
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.analyze_button)
        buttons.addStretch()
        grid.addLayout(buttons, 2, 0, 1, 5)
        root.addWidget(frame)

        cards = QHBoxLayout()
        self.score_card = self._card("Fingerprint Score", "0")
        self.class_card = self._card("Classification", "—")
        self.hands_card = self._card("Hands", "0")
        self.risk_card = self._card("Adaptation Risk", "—")
        for card in (
            self.score_card, self.class_card,
            self.hands_card, self.risk_card,
        ):
            cards.addWidget(card)
        root.addLayout(cards)

        self.summary_label = QLabel("Profil seçip fingerprint üret.")
        self.summary_label.setObjectName("FingerprintSummary")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        body = QHBoxLayout()
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(
            [label for _key, label in self.COLUMNS]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMinimumWidth(400)
        body.addWidget(self.table, 3)
        body.addWidget(self.notes, 2)
        root.addLayout(body, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)

        self.setStyleSheet(
            """
            QFrame#FingerprintFilters {
                background:#171b24; border:1px solid #303744;
                border-radius:12px;
            }
            QFrame#FingerprintCard {
                background:#1d222d; border:1px solid #343b49;
                border-radius:11px;
            }
            QLabel#FingerprintCardTitle { color:#9ca3af; font-size:12px; }
            QLabel#FingerprintCardValue { font-size:19px; font-weight:800; }
            QLabel#FingerprintSummary {
                padding:14px; background:#23262d;
                border:1px solid #3b4658; border-radius:10px;
                font-size:14px; font-weight:700;
            }
            QTextEdit {
                background:#11151d; border:1px solid #303744;
                border-radius:8px; padding:10px;
            }
            """
        )

    def _card(self, title: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("FingerprintCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 11, 15, 11)
        title_label = QLabel(title)
        title_label.setObjectName("FingerprintCardTitle")
        value_label = QLabel(value)
        value_label.setObjectName("FingerprintCardValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame.value_label = value_label
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return frame

    def refresh_filters(self) -> None:
        try:
            with self.service.profile.player_service.connect() as con:
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
                minimum_hands=self.minimum_hands.value(),
            )
            self.entity_combo.clear()
            for row in rows:
                self.entity_combo.addItem(
                    f"{row['player_name']} ({int(row['hands']):,} hands)",
                    row["player_name"],
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
                self, "Bot Fingerprint", "Önce profil yükleyip seç."
            )
            return

        self.load_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.status_label.setText("Tüm analiz motorları birleştiriliyor…")

        self.worker_thread = QThread(self)
        self.worker = FingerprintWorker(
            self.database_path,
            mode=str(self.mode_combo.currentData()),
            entity_name=entity,
            site=str(self.site_combo.currentData() or ""),
            stakes=str(self.stakes_combo.currentData() or ""),
            minimum_hands=self.minimum_hands.value(),
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
        self.score_card.value_label.setText(
            f"{float(report.get('overall_score', 0)):.0f}"
        )
        self.class_card.value_label.setText(str(report.get("classification", "—")))
        self.hands_card.value_label.setText(
            f"{int(report.get('hands', 0)):,}".replace(",", ".")
        )
        self.risk_card.value_label.setText(
            str(report.get("adaptation_risk", "—"))
        )
        self.summary_label.setText(str(report.get("summary", "")))

        dimensions = report.get("dimensions", [])
        self.table.clearContents()
        self.table.setRowCount(len(dimensions))
        for row_index, row in enumerate(dimensions):
            values = [
                row["label"],
                f"{float(row['score']):.0f}",
                row["value"],
                row["note"],
            ]
            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column_index == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_index, column_index, item)

        lines = ["STRATEGY TAGS", "-------------"]
        for tag in report.get("tags", []):
            lines.append(f"• {tag}")

        lines.extend(["", "STRENGTHS", "---------"])
        for note in report.get("strengths", []):
            lines.append(f"• {note}")

        lines.extend(["", "LEAKS / WATCHLIST", "-----------------"])
        for note in report.get("leaks", []):
            lines.append(f"• {note}")

        best_sizes = report.get("best_sizes", [])
        if best_sizes:
            lines.extend(["", "BEST SIZE BY POSITION", "---------------------"])
            for row in best_sizes:
                lines.append(
                    f"• {row['position']}: {row['size_bucket']} "
                    f"({row['score']:.0f}, {row['confidence']})"
                )

        self.notes.setPlainText("\n".join(lines))
        self.status_label.setText(
            f"{len(dimensions)} DNA boyutu analiz edildi."
        )

    @Slot(str)
    def _failed(self, message: str) -> None:
        QMessageBox.critical(self, "Fingerprint Hatası", message)
        self.status_label.setText("Fingerprint üretilemedi.")

    def _cleanup(self) -> None:
        self.load_button.setEnabled(True)
        self.analyze_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
