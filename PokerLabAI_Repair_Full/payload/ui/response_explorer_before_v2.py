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
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.response_explorer_service import (
    ResponseExplorerService,
)


class ResponseWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        database_path: str,
        mode: str,
        entity_name: str,
        site: str,
        stakes: str,
        position: str,
        minimum_sample: int,
    ) -> None:
        super().__init__()

        self.service = ResponseExplorerService(
            database_path
        )
        self.args = {
            "mode": mode,
            "entity_name": entity_name,
            "site": site,
            "stakes": stakes,
            "position": position,
            "minimum_sample": minimum_sample,
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


class ResponseExplorer(QWidget):
    COLUMNS = [
        ("position", "Pozisyon"),
        ("size_bucket", "Open Size"),
        ("opens", "Open"),
        ("avg_size_bb", "Ort. Size"),

        ("pool_fold_preflop", "Pool Fold"),
        ("pool_call_preflop", "Pool Call"),
        ("pool_3bet_preflop", "Pool 3Bet"),
        ("preflop_sample", "PF Sample"),

        ("flop_fold_vs_cbet", "Flop Fold vs CBet"),
        ("flop_sample", "Flop Sample"),

        ("turn_fold_vs_barrel", "Turn Fold vs Barrel"),
        ("turn_sample", "Turn Sample"),

        ("river_fold_vs_barrel", "River Fold vs Barrel"),
        ("river_sample", "River Sample"),

        ("response_score", "Response Score"),
        ("confidence", "Güven"),
        ("exploit_note", "Exploit"),
    ]

    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = database_path
        self.service = ResponseExplorerService(
            database_path
        )
        self.worker_thread: QThread | None = None
        self.worker: ResponseWorker | None = None

        self._build_ui()

        QTimer.singleShot(
            100,
            self.refresh_filters,
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            22,
            22,
            22,
            22,
        )
        root.setSpacing(13)

        title = QLabel("Pool Response Explorer v1")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Bot open size gruplarına poolun preflop ve postflop "
            "nasıl cevap verdiğini ölçer."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName("ResponseFilters")

        grid = QGridLayout(filters)
        grid.setContentsMargins(
            15,
            15,
            15,
            15,
        )

        self.mode_combo = QComboBox()
        self.mode_combo.addItem(
            "Player",
            "PLAYER",
        )
        self.mode_combo.addItem(
            "Alias Group",
            "ALIAS",
        )

        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumWidth(240)

        self.site_combo = QComboBox()
        self.site_combo.addItem(
            "Tüm Siteler",
            "",
        )

        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem(
            "Tüm Limitler",
            "",
        )

        self.position_combo = QComboBox()

        for label, value in [
            ("Tüm Pozisyonlar", ""),
            ("UTG", "UTG"),
            ("UTG+1", "UTG+1"),
            ("HJ", "HJ"),
            ("CO", "CO"),
            ("BTN", "BTN"),
            ("SB", "SB"),
            ("BB", "BB"),
        ]:
            self.position_combo.addItem(
                label,
                value,
            )

        self.minimum_sample = QSpinBox()
        self.minimum_sample.setRange(
            1,
            1_000_000,
        )
        self.minimum_sample.setValue(30)
        self.minimum_sample.setSingleStep(10)

        labels = [
            "Mod",
            "Oyuncu / Alias",
            "Site",
            "Stakes",
            "Pozisyon",
            "Min Sample",
        ]
        widgets = [
            self.mode_combo,
            self.entity_combo,
            self.site_combo,
            self.stakes_combo,
            self.position_combo,
            self.minimum_sample,
        ]

        for index, (
            label,
            widget,
        ) in enumerate(
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

        self.load_button = QPushButton(
            "Oyuncu/Alias Yükle"
        )
        self.analyze_button = QPushButton(
            "Pool Response Analiz Et"
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

        grid.addLayout(
            buttons,
            2,
            0,
            1,
            6,
        )

        root.addWidget(filters)

        cards = QHBoxLayout()

        self.opens_card = self._card(
            "Open",
            "0",
        )
        self.best_card = self._card(
            "En Güçlü Response",
            "—",
        )
        self.score_card = self._card(
            "Response Score",
            "0",
        )
        self.fold_card = self._card(
            "Pool Fold",
            "0.00%",
        )
        self.call_card = self._card(
            "Pool Call",
            "0.00%",
        )
        self.three_bet_card = self._card(
            "Pool 3Bet",
            "0.00%",
        )

        for card in (
            self.opens_card,
            self.best_card,
            self.score_card,
            self.fold_card,
            self.call_card,
            self.three_bet_card,
        ):
            cards.addWidget(card)

        root.addLayout(cards)

        self.summary_label = QLabel(
            "Profil seçip analizi başlat."
        )
        self.summary_label.setObjectName(
            "ResponseSummary"
        )
        self.summary_label.setWordWrap(True)

        root.addWidget(self.summary_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName(
            "PageSubtitle"
        )

        root.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(
            len(self.COLUMNS)
        )
        self.table.setHorizontalHeaderLabels(
            [
                label
                for _key, label in self.COLUMNS
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

        for index in range(
            len(self.COLUMNS) - 1
        ):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        header.setSectionResizeMode(
            len(self.COLUMNS) - 1,
            QHeaderView.ResizeMode.Stretch,
        )

        root.addWidget(
            self.table,
            1,
        )

        warning = QLabel(
            "Postflop fold oranları yalnızca heads-up spotlarda ve "
            "gerçek c-bet/barrel opportunity oluştuğunda hesaplanır."
        )
        warning.setObjectName("PageSubtitle")
        warning.setWordWrap(True)

        root.addWidget(warning)

        self.setStyleSheet(
            """
            QFrame#ResponseFilters {
                background:#171b24;
                border:1px solid #303744;
                border-radius:12px;
            }

            QFrame#ResponseCard {
                background:#1d222d;
                border:1px solid #343b49;
                border-radius:11px;
            }

            QLabel#ResponseCardTitle {
                color:#9ca3af;
                font-size:12px;
            }

            QLabel#ResponseCardValue {
                font-size:20px;
                font-weight:800;
            }

            QLabel#ResponseSummary {
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
        frame.setObjectName("ResponseCard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            15,
            11,
            15,
            11,
        )

        title_label = QLabel(title)
        title_label.setObjectName(
            "ResponseCardTitle"
        )

        value_label = QLabel(value)
        value_label.setObjectName(
            "ResponseCardValue"
        )
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
            with self.service.connect() as con:
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
            self.site_combo.addItem(
                "Tüm Siteler",
                "",
            )

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

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Response Filtre Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def load_entities(self) -> None:
        try:
            rows = self.service.available_entities(
                mode=str(
                    self.mode_combo.currentData()
                ),
                site=str(
                    self.site_combo.currentData()
                    or ""
                ),
                stakes=str(
                    self.stakes_combo.currentData()
                    or ""
                ),
                minimum_hands=100,
            )

            self.entity_combo.clear()

            for name, hands in rows:
                self.entity_combo.addItem(
                    f"{name} ({hands:,} hands)",
                    name,
                )

            self.status_label.setText(
                f"{len(rows)} profil yüklendi."
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Response Profil Hatası",
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
                "Pool Response Explorer",
                "Önce profil yükleyip seç.",
            )
            return

        self.load_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.status_label.setText(
            "Pool response hesaplanıyor…"
        )

        self.worker_thread = QThread(self)
        self.worker = ResponseWorker(
            database_path=self.database_path,
            mode=str(
                self.mode_combo.currentData()
            ),
            entity_name=entity_name,
            site=str(
                self.site_combo.currentData()
                or ""
            ),
            stakes=str(
                self.stakes_combo.currentData()
                or ""
            ),
            position=str(
                self.position_combo.currentData()
                or ""
            ),
            minimum_sample=(
                self.minimum_sample.value()
            ),
        )

        self.worker.moveToThread(
            self.worker_thread
        )

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
        rows = report.get(
            "rows",
            [],
        )
        best = report.get(
            "best_bucket",
            {},
        )

        self._fill_table(rows)

        self.opens_card.value_label.setText(
            f"{int(report.get('total_opens', 0)):,}"
            .replace(",", ".")
        )

        if best:
            self.best_card.value_label.setText(
                f"{best['position']} "
                f"{best['size_bucket']}"
            )
            self.score_card.value_label.setText(
                f"{float(best['response_score']):.0f}"
            )
            self.fold_card.value_label.setText(
                f"{float(best['pool_fold_preflop']):.2f}%"
            )
            self.call_card.value_label.setText(
                f"{float(best['pool_call_preflop']):.2f}%"
            )
            self.three_bet_card.value_label.setText(
                f"{float(best['pool_3bet_preflop']):.2f}%"
            )
        else:
            self.best_card.value_label.setText("—")
            self.score_card.value_label.setText("0")
            self.fold_card.value_label.setText("0.00%")
            self.call_card.value_label.setText("0.00%")
            self.three_bet_card.value_label.setText("0.00%")

        self.summary_label.setText(
            str(report.get("summary") or "")
        )
        self.status_label.setText(
            f"{len(rows)} sizing grubu analiz edildi."
        )

    def _fill_table(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(rows))

        percent_keys = {
            "pool_fold_preflop",
            "pool_call_preflop",
            "pool_3bet_preflop",
            "flop_fold_vs_cbet",
            "turn_fold_vs_barrel",
            "river_fold_vs_barrel",
        }

        integer_keys = {
            "opens",
            "preflop_sample",
            "flop_sample",
            "turn_sample",
            "river_sample",
        }

        for row_index, row in enumerate(rows):
            for column_index, (
                key,
                _label,
            ) in enumerate(self.COLUMNS):
                value = row.get(
                    key,
                    "",
                )

                if key == "avg_size_bb":
                    display = f"{float(value or 0):.2f}x"
                elif key == "response_score":
                    display = f"{float(value or 0):.0f}"
                elif key in percent_keys:
                    display = f"{float(value or 0):.2f}"
                elif key in integer_keys:
                    display = str(int(value or 0))
                else:
                    display = str(value)

                item = QTableWidgetItem(display)

                if key not in {
                    "position",
                    "size_bucket",
                    "confidence",
                    "exploit_note",
                }:
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

    @Slot(str)
    def _analysis_failed(
        self,
        message: str,
    ) -> None:
        QMessageBox.critical(
            self,
            "Pool Response Hatası",
            message,
        )
        self.status_label.setText(
            "Analiz başarısız."
        )

    def _cleanup_worker(self) -> None:
        self.load_button.setEnabled(True)
        self.analyze_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
