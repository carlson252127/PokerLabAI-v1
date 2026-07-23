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

from services.showdown_analysis_service import (
    ShowdownAnalysisService,
)


class ShowdownWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        database_path: str,
        mode: str,
        entity_name: str,
        site: str,
        stakes: str,
    ) -> None:
        super().__init__()

        self.service = ShowdownAnalysisService(
            database_path
        )
        self.args = {
            "mode": mode,
            "entity_name": entity_name,
            "site": site,
            "stakes": stakes,
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


class ShowdownExplorer(QWidget):
    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = database_path
        self.service = ShowdownAnalysisService(
            database_path
        )

        self.worker_thread: QThread | None = None
        self.worker: ShowdownWorker | None = None
        self.filters_loaded = False

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("WWSF / W$SD Breakdown")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Oyuncu veya bot alias grubunun pot kazanma ve "
            "showdown başarısını pozisyonlara ayırır."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName("ShowdownFilters")

        grid = QGridLayout(filters)
        grid.setContentsMargins(16, 16, 16, 16)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Player", "PLAYER")
        self.mode_combo.addItem("Alias Group", "ALIAS")
        self.mode_combo.addItem("Alias vs Pool", "COMPARE")

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
            "WWSF / W$SD Analiz Et"
        )

        self.load_button.clicked.connect(
            self.load_entities
        )
        self.analyze_button.clicked.connect(
            self.run_analysis
        )

        button_row = QHBoxLayout()
        button_row.addWidget(self.load_button)
        button_row.addWidget(self.analyze_button)
        button_row.addStretch()

        grid.addLayout(
            button_row,
            2,
            0,
            1,
            5,
        )

        root.addWidget(filters)

        cards = QHBoxLayout()
        cards.setSpacing(11)

        self.hands_card = self._card(
            "Hands",
            "0",
        )
        self.flop_card = self._card(
            "Flop Seen",
            "0",
        )
        self.wwsf_card = self._card(
            "WWSF",
            "0.00%",
        )
        self.showdown_card = self._card(
            "Showdown",
            "0",
        )
        self.wsd_card = self._card(
            "W$SD",
            "0.00%",
        )
        self.river_bet_wsd_card = self._card(
            "River Bet WSD",
            "0.00%",
        )
        self.position_card = self._card(
            "En Güçlü Pozisyon",
            "—",
        )

        for card in (
            self.hands_card,
            self.flop_card,
            self.wwsf_card,
            self.showdown_card,
            self.wsd_card,
            self.river_bet_wsd_card,
            self.position_card,
        ):
            cards.addWidget(card)

        root.addLayout(cards)

        self.compare_label = QLabel("")
        self.compare_label.setObjectName(
            "ShowdownCompare"
        )
        self.compare_label.setWordWrap(True)
        self.compare_label.hide()

        root.addWidget(self.compare_label)

        self.summary_label = QLabel(
            "Profil seçip analizi başlat."
        )
        self.summary_label.setObjectName(
            "ShowdownSummary"
        )
        self.summary_label.setWordWrap(True)

        root.addWidget(self.summary_label)

        self.table = QTableWidget()
        self.table.setColumnCount(11)
        self.table.setHorizontalHeaderLabels(
            [
                "Pozisyon",
                "Hands",
                "Flop Seen",
                "WWSF",
                "Showdown",
                "W$SD",
                "Pot Won",
                "Flop Agg Reach",
                "Turn Agg Reach",
                "River Agg Reach",
                "Etki Skoru",
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

        for index in range(11):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        root.addWidget(
            self.table,
            1,
        )

        note = QLabel(
            "WWSF = flop gören ellerde potu kazanma oranı. "
            "W$SD = kart gösterilen showdownlarda potu kazanma oranı. "
            "SHOW aksiyonlarının parser tarafından kaydedilmiş olması gerekir."
        )
        note.setObjectName("PageSubtitle")
        note.setWordWrap(True)

        root.addWidget(note)

        self.status_label = QLabel("")
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)

        self.setStyleSheet(
            """
            QFrame#ShowdownFilters {
                background:#171b24;
                border:1px solid #303744;
                border-radius:12px;
            }

            QFrame#ShowdownCard {
                background:#1d222d;
                border:1px solid #343b49;
                border-radius:11px;
            }

            QLabel#ShowdownCardTitle {
                color:#9ca3af;
                font-size:12px;
            }

            QLabel#ShowdownCardValue {
                font-size:21px;
                font-weight:800;
            }

            QLabel#ShowdownSummary,
            QLabel#ShowdownCompare {
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
        frame.setObjectName("ShowdownCard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            15,
            11,
            15,
            11,
        )

        title_label = QLabel(title)
        title_label.setObjectName(
            "ShowdownCardTitle"
        )

        value_label = QLabel(value)
        value_label.setObjectName(
            "ShowdownCardValue"
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
                "Showdown Filtre Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def load_entities(self) -> None:
        try:
            entities = self.service.available_entities(
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
                minimum_hands=self.minimum_hands.value(),
            )

            self.entity_combo.clear()

            for name, hands in entities:
                self.entity_combo.addItem(
                    f"{name} ({hands:,} hands)",
                    name,
                )

            self.status_label.setText(
                f"{len(entities)} profil yüklendi."
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Profil Yükleme Hatası",
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
                "WWSF / W$SD",
                "Önce profil listesini yükleyip seçim yap.",
            )
            return

        self.load_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.status_label.setText(
            "WWSF / W$SD analizi hesaplanıyor…"
        )

        self.worker_thread = QThread(self)
        self.worker = ShowdownWorker(
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
        result: dict[str, Any],
    ) -> None:
        entity = result.get("entity", {})
        pool = result.get("pool", {})

        self.hands_card.value_label.setText(
            f"{int(entity.get('hands', 0)):,}"
            .replace(",", ".")
        )
        self.flop_card.value_label.setText(
            f"{int(entity.get('flop_seen', 0)):,}"
            .replace(",", ".")
        )
        self.wwsf_card.value_label.setText(
            f"{float(entity.get('wwsf', 0.0)):.2f}%"
        )
        self.showdown_card.value_label.setText(
            f"{int(entity.get('showdown', 0)):,}"
            .replace(",", ".")
        )
        self.wsd_card.value_label.setText(
            f"{float(entity.get('wsd', 0.0)):.2f}%"
        )
        self.river_bet_wsd_card.value_label.setText(
            f"{float(entity.get('river_bet_wsd', 0.0)):.2f}%"
        )
        self.position_card.value_label.setText(
            str(
                entity.get(
                    "strongest_position",
                    "—",
                )
            )
        )

        self.summary_label.setText(
            str(entity.get("summary", ""))
        )

        if pool:
            self.compare_label.show()
            self.compare_label.setText(
                "Alias vs Pool — "
                f"WWSF Δ: "
                f"{float(entity.get('wwsf', 0.0)) - float(pool.get('wwsf', 0.0)):+.2f} | "
                f"W$SD Δ: "
                f"{float(entity.get('wsd', 0.0)) - float(pool.get('wsd', 0.0)):+.2f} | "
                f"Pot Won Δ: "
                f"{float(entity.get('pot_won', 0.0)) - float(pool.get('pot_won', 0.0)):+.2f}"
            )
        else:
            self.compare_label.hide()

        rows = entity.get(
            "by_position",
            [],
        )
        self._fill_table(rows)

        self.status_label.setText(
            f"{len(rows)} pozisyon grubu analiz edildi."
        )

    def _fill_table(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(rows))

        for row_index, row in enumerate(rows):
            values = [
                row["position"],
                str(row["hands"]),
                str(row["flop_seen"]),
                f"{row['wwsf']:.2f}",
                str(row["showdown"]),
                f"{row['wsd']:.2f}",
                f"{row['pot_won']:.2f}",
                f"{row['flop_aggression_reach']:.2f}",
                f"{row['turn_aggression_reach']:.2f}",
                f"{row['river_aggression_reach']:.2f}",
                f"{row['impact_score']:.2f}",
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(
                    str(value)
                )

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

    @Slot(str)
    def _analysis_failed(
        self,
        message: str,
    ) -> None:
        QMessageBox.critical(
            self,
            "WWSF / W$SD Analiz Hatası",
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
