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
    QVBoxLayout,
    QWidget,
)

from services.metric_validator_service import (
    MetricValidatorService,
)


class MetricValidatorWorker(QObject):
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

        self.service = MetricValidatorService(
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
                self.service.validate(**self.args)
            )
        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )


class MetricValidatorExplorer(QWidget):
    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = database_path
        self.service = MetricValidatorService(
            database_path
        )

        self.worker_thread: QThread | None = None
        self.worker: MetricValidatorWorker | None = None
        self.filters_loaded = False

        self._build_ui()

        # main_window page-index sırasına bağlı kalmadan ilk açılışta
        # filtreleri doğrudan veritabanından yükle.
        QTimer.singleShot(
            0,
            self.refresh_filters,
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Metric Validator")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "WWSF ve W$SD hesaplarının ham sayaçlarını doğrular."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName("ValidatorFilters")

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
        self.validate_button = QPushButton(
            "Sayaçları Doğrula"
        )

        self.load_button.clicked.connect(
            self.load_entities
        )
        self.validate_button.clicked.connect(
            self.run_validation
        )

        button_row = QHBoxLayout()
        button_row.addWidget(self.load_button)
        button_row.addWidget(self.validate_button)
        button_row.addStretch()

        grid.addLayout(button_row, 2, 0, 1, 5)
        root.addWidget(filters)

        cards = QHBoxLayout()
        cards.setSpacing(10)

        self.hands_card = self._card(
            "Player-Hand Rows",
            "0",
        )
        self.distinct_card = self._card(
            "Distinct Hands",
            "0",
        )
        self.flop_card = self._card(
            "Saw Flop",
            "0",
        )
        self.win_card = self._card(
            "Saw Flop + Won",
            "0",
        )
        self.wwsf_card = self._card(
            "WWSF",
            "0.00%",
        )
        self.wsd_card = self._card(
            "W$SD",
            "0.00%",
        )

        for card in (
            self.hands_card,
            self.distinct_card,
            self.flop_card,
            self.win_card,
            self.wwsf_card,
            self.wsd_card,
        ):
            cards.addWidget(card)

        root.addLayout(cards)

        self.formula_label = QLabel(
            "WWSF = Saw Flop + Won / Saw Flop\n"
            "W$SD = Showdown Wins / Showdown"
        )
        self.formula_label.setObjectName("ValidatorSummary")
        self.formula_label.setWordWrap(True)

        root.addWidget(self.formula_label)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(
            [
                "Sayaç",
                "Değer",
            ]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        root.addWidget(self.table, 1)

        self.diagnosis_label = QLabel("")
        self.diagnosis_label.setObjectName(
            "ValidatorDiagnosis"
        )
        self.diagnosis_label.setWordWrap(True)

        root.addWidget(self.diagnosis_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)

        self.setStyleSheet(
            """
            QFrame#ValidatorFilters {
                background:#171b24;
                border:1px solid #303744;
                border-radius:12px;
            }

            QFrame#ValidatorCard {
                background:#1d222d;
                border:1px solid #343b49;
                border-radius:11px;
            }

            QLabel#ValidatorCardTitle {
                color:#9ca3af;
                font-size:12px;
            }

            QLabel#ValidatorCardValue {
                font-size:21px;
                font-weight:800;
            }

            QLabel#ValidatorSummary,
            QLabel#ValidatorDiagnosis {
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
        frame.setObjectName("ValidatorCard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 11, 15, 11)

        title_label = QLabel(title)
        title_label.setObjectName(
            "ValidatorCardTitle"
        )

        value_label = QLabel(value)
        value_label.setObjectName(
            "ValidatorCardValue"
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

        # Sayfa her görünür olduğunda yeni import edilen site ve
        # stakes değerlerini tekrar oku.
        QTimer.singleShot(
            0,
            self.refresh_filters,
        )

    def refresh_filters(self) -> None:
        try:
            current_site = self.site_combo.currentData()
            current_stakes = self.stakes_combo.currentData()

            with self.service.connect() as con:
                sites = con.execute(
                    """
                    SELECT DISTINCT TRIM(site) AS site
                    FROM hands
                    WHERE site IS NOT NULL
                      AND TRIM(site) <> ''
                    ORDER BY site
                    """
                ).fetchall()

                stakes = con.execute(
                    """
                    SELECT DISTINCT TRIM(stakes) AS stakes
                    FROM hands
                    WHERE stakes IS NOT NULL
                      AND TRIM(stakes) <> ''
                    ORDER BY stakes
                    """
                ).fetchall()

            self.site_combo.blockSignals(True)
            self.stakes_combo.blockSignals(True)

            self.site_combo.clear()
            self.site_combo.addItem("Tüm Siteler", "")

            for row in sites:
                site = str(row[0]).strip()

                if site:
                    self.site_combo.addItem(
                        site,
                        site,
                    )

            self.stakes_combo.clear()
            self.stakes_combo.addItem(
                "Tüm Limitler",
                "",
            )

            for row in stakes:
                stake = str(row[0]).strip()

                if stake:
                    self.stakes_combo.addItem(
                        stake,
                        stake,
                    )

            site_index = self.site_combo.findData(
                current_site
            )

            if site_index >= 0:
                self.site_combo.setCurrentIndex(
                    site_index
                )
            else:
                self.site_combo.setCurrentIndex(0)

            stakes_index = self.stakes_combo.findData(
                current_stakes
            )

            if stakes_index >= 0:
                self.stakes_combo.setCurrentIndex(
                    stakes_index
                )
            else:
                self.stakes_combo.setCurrentIndex(0)

            self.site_combo.blockSignals(False)
            self.stakes_combo.blockSignals(False)

            self.filters_loaded = True

        except Exception as exc:
            self.site_combo.blockSignals(False)
            self.stakes_combo.blockSignals(False)

            QMessageBox.critical(
                self,
                "Validator Filtre Hatası",
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

    def run_validation(self) -> None:
        if self.worker_thread is not None:
            return

        entity_name = str(
            self.entity_combo.currentData()
            or ""
        )

        if not entity_name:
            QMessageBox.information(
                self,
                "Metric Validator",
                "Önce profil listesini yükleyip seçim yap.",
            )
            return

        self.load_button.setEnabled(False)
        self.validate_button.setEnabled(False)
        self.status_label.setText(
            "Ham sayaçlar doğrulanıyor…"
        )

        self.worker_thread = QThread(self)
        self.worker = MetricValidatorWorker(
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
            self._validation_finished
        )
        self.worker.failed.connect(
            self._validation_failed
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
    def _validation_finished(
        self,
        result: dict[str, Any],
    ) -> None:
        self.hands_card.value_label.setText(
            self._format(result["player_hand_rows"])
        )
        self.distinct_card.value_label.setText(
            self._format(result["distinct_hands"])
        )
        self.flop_card.value_label.setText(
            self._format(result["saw_flop"])
        )
        self.win_card.value_label.setText(
            self._format(result["saw_flop_and_won"])
        )
        self.wwsf_card.value_label.setText(
            f"{result['wwsf']:.2f}%"
        )
        self.wsd_card.value_label.setText(
            f"{result['wsd']:.2f}%"
        )

        counters = [
            ("Player-Hand Rows", result["player_hand_rows"]),
            ("Distinct Hands", result["distinct_hands"]),
            ("Preflop Folds", result["preflop_folds"]),
            ("Hands Reaching Flop", result["hands_reaching_flop"]),
            ("Saw Flop", result["saw_flop"]),
            ("Player Flop Actions", result["player_flop_actions"]),
            ("Player Turn Actions", result["player_turn_actions"]),
            ("Player River Actions", result["player_river_actions"]),
            ("Pot Wins", result["pot_wins"]),
            ("Saw Flop + Won", result["saw_flop_and_won"]),
            ("Showdown", result["showdown"]),
            ("Showdown Wins", result["showdown_wins"]),
            ("Preflop Fold Rate", f"{result['preflop_fold_rate']:.2f}%"),
            ("Flop Seen Rate", f"{result['flop_seen_rate']:.2f}%"),
            ("WWSF", f"{result['wwsf']:.2f}%"),
            ("W$SD", f"{result['wsd']:.2f}%"),
        ]

        self.table.clearContents()
        self.table.setRowCount(len(counters))

        for row_index, (label, value) in enumerate(counters):
            self.table.setItem(
                row_index,
                0,
                QTableWidgetItem(str(label)),
            )

            value_item = QTableWidgetItem(
                self._format(value)
                if isinstance(value, int)
                else str(value)
            )
            value_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
            )

            self.table.setItem(
                row_index,
                1,
                value_item,
            )

        self.formula_label.setText(
            f"WWSF = {self._format(result['saw_flop_and_won'])} "
            f"/ {self._format(result['saw_flop'])} "
            f"= {result['wwsf']:.2f}%\n"
            f"W$SD = {self._format(result['showdown_wins'])} "
            f"/ {self._format(result['showdown'])} "
            f"= {result['wsd']:.2f}%"
        )

        diagnosis = result.get("diagnosis", [])

        self.diagnosis_label.setText(
            "Teşhis:\n• "
            + "\n• ".join(diagnosis)
        )

        self.status_label.setText(
            "Doğrulama tamamlandı."
        )

    @Slot(str)
    def _validation_failed(
        self,
        message: str,
    ) -> None:
        QMessageBox.critical(
            self,
            "Metric Validator Hatası",
            message,
        )
        self.status_label.setText(
            "Doğrulama başarısız."
        )

    def _cleanup_worker(self) -> None:
        self.load_button.setEnabled(True)
        self.validate_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None

    def _format(
        self,
        value: int,
    ) -> str:
        return f"{int(value):,}".replace(",", ".")
