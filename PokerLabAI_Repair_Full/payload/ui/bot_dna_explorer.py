from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QObject,
    QThread,
    Signal,
    Slot,
    Qt,
    QTimer,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.bot_dna_service import BotDNAService


class BotDNAWorker(QObject):
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

        self.service = BotDNAService(database_path)
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
                self.service.build_dna(**self.args)
            )
        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )


class BotDNAExplorer(QWidget):
    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = database_path
        self.service = BotDNAService(database_path)

        self.worker_thread: QThread | None = None
        self.worker: BotDNAWorker | None = None

        self._build_ui()

        QTimer.singleShot(
            100,
            self.refresh_filters,
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(13)

        title = QLabel("Bot DNA Engine v1")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Preflop, postflop ve showdown davranışlarını "
            "tek bir yorumlanabilir strateji profiline dönüştürür."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName("BotDNAFilters")

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

        self.load_button = QPushButton(
            "Profil Listesini Yükle"
        )
        self.build_button = QPushButton(
            "DNA Profilini Oluştur"
        )

        self.load_button.clicked.connect(
            self.load_entities
        )
        self.build_button.clicked.connect(
            self.run_analysis
        )

        buttons = QHBoxLayout()
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.build_button)
        buttons.addStretch()

        grid.addLayout(buttons, 2, 0, 1, 5)
        root.addWidget(filters)

        cards = QHBoxLayout()
        self.profile_card = self._card("Profil", "—")
        self.hands_card = self._card("Hands", "0")
        self.type_card = self._card("DNA Tipi", "—")
        self.style_card = self._card("Postflop Stil", "—")

        for card in (
            self.profile_card,
            self.hands_card,
            self.type_card,
            self.style_card,
        ):
            cards.addWidget(card)

        root.addLayout(cards)

        self.summary_label = QLabel(
            "Profil seçip DNA analizini başlat."
        )
        self.summary_label.setObjectName("BotDNASummary")
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        dimension_frame = QFrame()
        dimension_frame.setObjectName("BotDNADimensions")
        dimension_layout = QGridLayout(dimension_frame)
        dimension_layout.setContentsMargins(14, 14, 14, 14)

        self.dimension_bars: dict[str, QProgressBar] = {}
        dimension_names = [
            "Preflop Baskı",
            "Flop Baskı",
            "Turn Baskı",
            "River Baskı",
            "Pot Kazanma",
            "Showdown Kalitesi",
            "Sizing Baskısı",
        ]

        for index, name in enumerate(dimension_names):
            label = QLabel(name)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(50)
            bar.setFormat("%v / 100")

            row = index // 2
            column = (index % 2) * 2

            dimension_layout.addWidget(
                label,
                row,
                column,
            )
            dimension_layout.addWidget(
                bar,
                row,
                column + 1,
            )

            self.dimension_bars[name] = bar

        root.addWidget(dimension_frame)

        body = QHBoxLayout()

        self.metric_table = QTableWidget()
        self.metric_table.setColumnCount(6)
        self.metric_table.setHorizontalHeaderLabels(
            [
                "Kategori",
                "Metrik",
                "Bot/Oyuncu",
                "Pool",
                "Delta",
                "Yorum",
            ]
        )
        self.metric_table.setAlternatingRowColors(True)
        self.metric_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.metric_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.metric_table.verticalHeader().setVisible(False)

        header = self.metric_table.horizontalHeader()

        for index in range(5):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        header.setSectionResizeMode(
            5,
            QHeaderView.ResizeMode.Stretch,
        )

        self.notes_text = QTextEdit()
        self.notes_text.setReadOnly(True)
        self.notes_text.setMinimumWidth(380)

        body.addWidget(self.metric_table, 3)
        body.addWidget(self.notes_text, 2)

        root.addLayout(body, 1)

        self.warning_label = QLabel(
            "3Bet opportunity hesabı doğrulanana kadar "
            "DNA skoruna dahil edilmez."
        )
        self.warning_label.setObjectName("PageSubtitle")
        self.warning_label.setWordWrap(True)

        root.addWidget(self.warning_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)

        self.setStyleSheet(
            """
            QFrame#BotDNAFilters,
            QFrame#BotDNADimensions {
                background:#171b24;
                border:1px solid #303744;
                border-radius:12px;
            }

            QFrame#BotDNACard {
                background:#1d222d;
                border:1px solid #343b49;
                border-radius:11px;
            }

            QLabel#BotDNACardTitle {
                color:#9ca3af;
                font-size:12px;
            }

            QLabel#BotDNACardValue {
                font-size:20px;
                font-weight:800;
            }

            QLabel#BotDNASummary {
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
        frame.setObjectName("BotDNACard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 11, 15, 11)

        title_label = QLabel(title)
        title_label.setObjectName("BotDNACardTitle")

        value_label = QLabel(value)
        value_label.setObjectName("BotDNACardValue")
        value_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        frame.value_label = value_label

        layout.addWidget(title_label)
        layout.addWidget(value_label)

        return frame

    def showEvent(self, event) -> None:
        super().showEvent(event)

        QTimer.singleShot(
            100,
            self.refresh_filters,
        )

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
                    self.site_combo.addItem(value, value)

            self.stakes_combo.clear()
            self.stakes_combo.addItem("Tüm Limitler", "")

            for row in stakes:
                value = str(row[0]).strip()

                if value:
                    self.stakes_combo.addItem(value, value)

            site_index = self.site_combo.findData(current_site)

            if site_index >= 0:
                self.site_combo.setCurrentIndex(site_index)

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
                "Bot DNA Filtre Hatası",
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
                "Bot DNA Profil Hatası",
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
                "Bot DNA",
                "Önce profil listesini yükleyip seçim yap.",
            )
            return

        self.load_button.setEnabled(False)
        self.build_button.setEnabled(False)
        self.status_label.setText(
            "Bot DNA profili hesaplanıyor…"
        )

        self.worker_thread = QThread(self)
        self.worker = BotDNAWorker(
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
        self.worker_thread.started.connect(self.worker.run)
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
        classification = report["classification"]

        self.profile_card.value_label.setText(
            report["entity_name"]
        )
        self.hands_card.value_label.setText(
            f"{int(report['hands']):,}".replace(",", ".")
        )
        self.type_card.value_label.setText(
            classification["dna_type"]
        )
        self.style_card.value_label.setText(
            classification["postflop_style"]
        )

        self.summary_label.setText(report["summary"])

        for name, value in report["dimensions"].items():
            bar = self.dimension_bars.get(name)

            if bar:
                bar.setValue(round(float(value)))

        metrics = report["metrics"]

        self.metric_table.clearContents()
        self.metric_table.setRowCount(len(metrics))

        for row_index, row in enumerate(metrics):
            suffix = "x" if row["key"] == "avg_size_bb" else "%"

            values = [
                row["category"],
                row["label"],
                f"{row['entity']:.2f}{suffix}",
                f"{row['pool']:.2f}{suffix}",
                f"{row['delta']:+.2f}{suffix}",
                row["note"],
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))

                if 2 <= column_index <= 4:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )

                self.metric_table.setItem(
                    row_index,
                    column_index,
                    item,
                )

        lines = [
            "SINIFLANDIRMA",
            "--------------",
            f"DNA Tipi: {classification['dna_type']}",
            f"Preflop: {classification['preflop_style']}",
            f"Postflop: {classification['postflop_style']}",
            f"Showdown: {classification['showdown_style']}",
            "",
            "GÜÇLÜ ALANLAR",
            "-------------",
        ]

        strengths = report.get("strengths", [])

        if strengths:
            for row in strengths:
                lines.append(
                    f"• {row['label']}: {row['delta']:+.2f}"
                )
        else:
            lines.append("• Belirgin güçlü delta yok.")

        lines.extend(
            [
                "",
                "ZAYIF / DÜŞÜK ALANLAR",
                "--------------------",
            ]
        )

        weaknesses = report.get("weaknesses", [])

        if weaknesses:
            for row in weaknesses:
                lines.append(
                    f"• {row['label']}: {row['delta']:+.2f}"
                )
        else:
            lines.append("• Belirgin düşük delta yok.")

        lines.extend(
            [
                "",
                "İLK EXPLOIT NOTLARI",
                "-------------------",
            ]
        )

        for note in report.get("exploits", []):
            lines.append(f"• {note}")

        self.notes_text.setPlainText(
            "\n".join(lines)
        )

        self.warning_label.setText(report["warning"])
        self.status_label.setText(
            f"{len(metrics)} metrik DNA profiline işlendi."
        )

    @Slot(str)
    def _analysis_failed(
        self,
        message: str,
    ) -> None:
        QMessageBox.critical(
            self,
            "Bot DNA Hatası",
            message,
        )
        self.status_label.setText(
            "Bot DNA profili oluşturulamadı."
        )

    def _cleanup_worker(self) -> None:
        self.load_button.setEnabled(True)
        self.build_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
