from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.wsd_analyzer_service import WSDAnalyzerService


class WSDWorker(QObject):
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

        self.service = WSDAnalyzerService(database_path)
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
                self.service.analyze(**self.args)
            )
        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )


class WSDAnalyzerExplorer(QWidget):
    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = database_path
        self.service = WSDAnalyzerService(database_path)
        self.worker_thread: QThread | None = None
        self.worker: WSDWorker | None = None

        self._build_ui()
        QTimer.singleShot(100, self.refresh_filters)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(13)

        title = QLabel("W$SD Analyzer v1")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "W$SD farkını WTSD ve turn/river davranış deltalarıyla "
            "heuristic olarak açıklar."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName("WSDFilters")
        grid = QGridLayout(filters)
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

        self.minimum_hands = QSpinBox()
        self.minimum_hands.setRange(1, 100_000_000)
        self.minimum_hands.setValue(500)
        self.minimum_hands.setSingleStep(500)

        labels = [
            "Mod",
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

        self.load_button = QPushButton(
            "Profil Listesini Yükle"
        )
        self.analyze_button = QPushButton(
            "W$SD'yi Parçala"
        )

        self.load_button.clicked.connect(
            self.load_entities
        )
        self.analyze_button.clicked.connect(
            self.run_analysis
        )

        buttons = QHBoxLayout()
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.analyze_button)
        buttons.addStretch()

        grid.addLayout(buttons, 2, 0, 1, 5)
        root.addWidget(filters)

        cards = QHBoxLayout()
        self.entity_card = self._card(
            "Bot/Oyuncu W$SD",
            "0.00%",
        )
        self.pool_card = self._card(
            "Pool W$SD",
            "0.00%",
        )
        self.gap_card = self._card(
            "W$SD Delta",
            "+0.00",
        )
        self.wtsd_card = self._card(
            "WTSD Bot / Pool",
            "0.00 / 0.00",
        )
        self.sample_card = self._card(
            "Showdown Sample",
            "0",
        )

        for card in (
            self.entity_card,
            self.pool_card,
            self.gap_card,
            self.wtsd_card,
            self.sample_card,
        ):
            cards.addWidget(card)

        root.addLayout(cards)

        self.summary_label = QLabel(
            "Profil seçip W$SD analizini başlat."
        )
        self.summary_label.setObjectName("WSDSummary")
        self.summary_label.setWordWrap(True)

        root.addWidget(self.summary_label)

        body = QHBoxLayout()

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            [
                "Street",
                "Metrik",
                "Bot/Oyuncu",
                "Pool",
                "Delta",
                "Opportunity",
                "Tahmini Katkı",
                "Sample Weight",
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

        for index in range(8):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        self.insights = QTextEdit()
        self.insights.setReadOnly(True)
        self.insights.setMinimumWidth(360)

        body.addWidget(self.table, 3)
        body.addWidget(self.insights, 2)

        root.addLayout(body, 1)

        self.warning_label = QLabel(
            "Katkılar nedensel EV hesabı değildir."
        )
        self.warning_label.setObjectName("PageSubtitle")
        self.warning_label.setWordWrap(True)

        self.status_label = QLabel("")
        self.status_label.setObjectName("PageSubtitle")

        root.addWidget(self.warning_label)
        root.addWidget(self.status_label)

        self.setStyleSheet(
            """
            QFrame#WSDFilters {
                background:#171b24;
                border:1px solid #303744;
                border-radius:12px;
            }

            QFrame#WSDCard {
                background:#1d222d;
                border:1px solid #343b49;
                border-radius:11px;
            }

            QLabel#WSDCardTitle {
                color:#9ca3af;
                font-size:12px;
            }

            QLabel#WSDCardValue {
                font-size:19px;
                font-weight:800;
            }

            QLabel#WSDSummary {
                padding:14px;
                background:#23262d;
                border:1px solid #3b4658;
                border-radius:10px;
                font-size:14px;
                font-weight:700;
            }

            QTextEdit {
                background:#11151d;
                border:1px solid #303744;
                border-radius:8px;
                padding:10px;
            }
            """
        )

    def _card(
        self,
        title: str,
        value: str,
    ) -> QFrame:
        frame = QFrame()
        frame.setObjectName("WSDCard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 11, 15, 11)

        title_label = QLabel(title)
        title_label.setObjectName("WSDCardTitle")

        value_label = QLabel(value)
        value_label.setObjectName("WSDCardValue")
        value_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        frame.value_label = value_label

        layout.addWidget(title_label)
        layout.addWidget(value_label)

        return frame

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(100, self.refresh_filters)

    def refresh_filters(self) -> None:
        try:
            current_site = self.site_combo.currentData()
            current_stakes = self.stakes_combo.currentData()

            with self.service.profile_service.player_service.connect() as con:
                sites = con.execute(
                    """
                    SELECT DISTINCT TRIM(site)
                    FROM hands
                    WHERE site IS NOT NULL
                      AND TRIM(site) <> ''
                    ORDER BY 1
                    """
                ).fetchall()

                stakes = con.execute(
                    """
                    SELECT DISTINCT TRIM(stakes)
                    FROM hands
                    WHERE stakes IS NOT NULL
                      AND TRIM(stakes) <> ''
                    ORDER BY 1
                    """
                ).fetchall()

            self.site_combo.clear()
            self.site_combo.addItem("Tüm Siteler", "")

            for row in sites:
                value = str(row[0]).strip()

                if value:
                    self.site_combo.addItem(
                        value,
                        value,
                    )

            self.stakes_combo.clear()
            self.stakes_combo.addItem(
                "Tüm Limitler",
                "",
            )

            for row in stakes:
                value = str(row[0]).strip()

                if value:
                    self.stakes_combo.addItem(
                        value,
                        value,
                    )

            site_index = self.site_combo.findData(
                current_site
            )

            if site_index >= 0:
                self.site_combo.setCurrentIndex(
                    site_index
                )

            stakes_index = self.stakes_combo.findData(
                current_stakes
            )

            if stakes_index >= 0:
                self.stakes_combo.setCurrentIndex(
                    stakes_index
                )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "W$SD Filtre Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def load_entities(self) -> None:
        try:
            rows = self.service.available_entities(
                mode=str(self.mode_combo.currentData()),
                site=str(self.site_combo.currentData() or ""),
                stakes=str(
                    self.stakes_combo.currentData() or ""
                ),
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
                "W$SD Profil Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def run_analysis(self) -> None:
        if self.worker_thread is not None:
            return

        entity_name = str(
            self.entity_combo.currentData()
            or ""
        )

        if not entity_name:
            QMessageBox.information(
                self,
                "W$SD Analyzer",
                "Önce profil listesini yükleyip seçim yap.",
            )
            return

        self.load_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.status_label.setText(
            "W$SD farkı parçalanıyor…"
        )

        self.worker_thread = QThread(self)
        self.worker = WSDWorker(
            database_path=self.database_path,
            mode=str(self.mode_combo.currentData()),
            entity_name=entity_name,
            site=str(self.site_combo.currentData() or ""),
            stakes=str(
                self.stakes_combo.currentData() or ""
            ),
            minimum_hands=self.minimum_hands.value(),
        )

        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(
            self.worker.run
        )
        self.worker.finished.connect(
            self._analysis_finished
        )
        self.worker.failed.connect(
            self._analysis_failed
        )
        self.worker.finished.connect(
            self.worker_thread.quit
        )
        self.worker.failed.connect(
            self.worker_thread.quit
        )
        self.worker_thread.finished.connect(
            self._cleanup_worker
        )
        self.worker_thread.start()

    @Slot(dict)
    def _analysis_finished(
        self,
        report: dict[str, Any],
    ) -> None:
        self.entity_card.value_label.setText(
            f"{report['entity_wsd']:.2f}%"
        )
        self.pool_card.value_label.setText(
            f"{report['pool_wsd']:.2f}%"
        )
        self.gap_card.value_label.setText(
            f"{report['gap']:+.2f}"
        )
        self.wtsd_card.value_label.setText(
            f"{report['entity_wtsd']:.2f} / "
            f"{report['pool_wtsd']:.2f}"
        )
        self.sample_card.value_label.setText(
            f"{int(report['showdown']):,}"
            .replace(",", ".")
        )

        self.summary_label.setText(report["summary"])
        self.warning_label.setText(report["warning"])

        components = report["components"]

        self.table.clearContents()
        self.table.setRowCount(len(components))

        for row_index, row in enumerate(components):
            suffix = (
                "x"
                if row["key"] == "avg_size_bb"
                else "%"
            )

            values = [
                row["street"],
                row["label"],
                f"{row['entity']:.2f}{suffix}",
                f"{row['pool']:.2f}{suffix}",
                f"{row['delta']:+.2f}{suffix}",
                str(row["opportunity"]),
                f"{row['attribution']:+.2f}",
                f"{row['sample_factor']:.2f}",
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))

                if column_index >= 2:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )

                self.table.setItem(
                    row_index,
                    column_index,
                    item,
                )

        lines = [
            "W$SD ATTRIBUTION",
            "---------------",
        ]

        for note in report.get("insights", []):
            lines.append(f"• {note}")

        lines.extend(
            [
                "",
                "STREET TOPLAMLARI",
                "-----------------",
            ]
        )

        for row in report.get("grouped", []):
            lines.append(
                f"• {row['street']}: "
                f"{row['attribution']:+.2f}"
            )

        self.insights.setPlainText(
            "\n".join(lines)
        )

        self.status_label.setText(
            f"{len(components)} davranış metriği analiz edildi."
        )

    @Slot(str)
    def _analysis_failed(
        self,
        message: str,
    ) -> None:
        QMessageBox.critical(
            self,
            "W$SD Analyzer Hatası",
            message,
        )
        self.status_label.setText(
            "W$SD analizi başarısız."
        )

    def _cleanup_worker(self) -> None:
        self.load_button.setEnabled(True)
        self.analyze_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
