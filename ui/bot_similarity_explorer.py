from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
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

from services.bot_similarity_service import (
    BotSimilarityService,
)


class NumericTableItem(QTableWidgetItem):
    def __init__(self, text: str, numeric_value: float) -> None:
        super().__init__(text)
        self.numeric_value = float(numeric_value)

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, NumericTableItem):
            return self.numeric_value < other.numeric_value
        return super().__lt__(other)


class EntityLoadWorker(QObject):
    finished = Signal(list, dict)
    failed = Signal(str)

    def __init__(
        self,
        database_path: str,
        filters: dict[str, Any],
    ) -> None:
        super().__init__()
        self.service = BotSimilarityService(database_path)
        self.filters = filters

    @Slot()
    def run(self) -> None:
        try:
            rows = self.service.get_entities(**self.filters)
            self.finished.emit(
                rows,
                dict(self.service.last_filter_diagnostics),
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class SimilarityWorker(QObject):
    finished = Signal(dict, list)
    failed = Signal(str)

    def __init__(
        self,
        database_path: str,
        reference_name: str,
        site: str,
        stakes: str,
        minimum_hands: int,
        minimum_vpip: float,
        minimum_pfr: float,
        large_open_threshold: float,
        turn_size_frequency_target: float | None,
        turn_size_frequency_tolerance: float,
        wwsf_target: float | None,
        wwsf_tolerance: float,
        use_aliases: bool,
    ) -> None:
        super().__init__()

        self.service = BotSimilarityService(database_path)
        self.reference_name = reference_name
        self.site = site
        self.stakes = stakes
        self.minimum_hands = minimum_hands
        self.minimum_vpip = minimum_vpip
        self.minimum_pfr = minimum_pfr
        self.large_open_threshold = large_open_threshold
        self.turn_size_frequency_target = turn_size_frequency_target
        self.turn_size_frequency_tolerance = turn_size_frequency_tolerance
        self.wwsf_target = wwsf_target
        self.wwsf_tolerance = wwsf_tolerance
        self.use_aliases = use_aliases

    @Slot()
    def run(self) -> None:
        try:
            reference, rows = self.service.compare(
                reference_name=self.reference_name,
                site=self.site,
                stakes=self.stakes,
                minimum_hands=self.minimum_hands,
                minimum_vpip=self.minimum_vpip,
                minimum_pfr=self.minimum_pfr,
                large_open_threshold=self.large_open_threshold,
                turn_size_frequency_target=self.turn_size_frequency_target,
                turn_size_frequency_tolerance=self.turn_size_frequency_tolerance,
                wwsf_target=self.wwsf_target,
                wwsf_tolerance=self.wwsf_tolerance,
                use_aliases=self.use_aliases,
                limit=500,
            )
            self.finished.emit(reference, rows)

        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )


class BotSimilarityExplorer(QWidget):
    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = database_path
        self.service = BotSimilarityService(database_path)

        self.worker_thread: QThread | None = None
        self.worker: SimilarityWorker | None = None
        self.load_thread: QThread | None = None
        self.load_worker: EntityLoadWorker | None = None
        self.filters_loaded = False

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Bot Similarity 2.3")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "VPIP/PFR, Fold to 3Bet, pozisyon bazlı büyük open, "
            "Turn CBet IP sizing ve WWSF ile doğrudan aday tarar; "
            "referans oyuncu kullanımı opsiyoneldir."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName("SimilarityFilters")

        grid = QGridLayout(filters)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")

        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.minimum_hands = QSpinBox()
        self.minimum_hands.setRange(1, 100000000)
        self.minimum_hands.setValue(750)
        self.minimum_hands.setSingleStep(250)

        self.minimum_vpip = QDoubleSpinBox()
        self.minimum_vpip.setRange(0.0, 100.0)
        self.minimum_vpip.setDecimals(1)
        self.minimum_vpip.setValue(30.0)
        self.minimum_vpip.setSingleStep(1.0)
        self.minimum_vpip.setSuffix(" %")

        self.minimum_pfr = QDoubleSpinBox()
        self.minimum_pfr.setRange(0.0, 100.0)
        self.minimum_pfr.setDecimals(1)
        self.minimum_pfr.setValue(20.0)
        self.minimum_pfr.setSingleStep(1.0)
        self.minimum_pfr.setSuffix(" %")

        self.large_open_threshold = QDoubleSpinBox()
        self.large_open_threshold.setRange(1.0, 10.0)
        self.large_open_threshold.setDecimals(1)
        self.large_open_threshold.setValue(3.4)
        self.large_open_threshold.setSingleStep(0.1)
        self.large_open_threshold.setSuffix("x")
        self.large_open_threshold.setToolTip(
            "Aday eleme filtresi değildir; pozisyon sütunlarındaki "
            "büyük open frekansının alt sınırıdır."
        )
        self.large_open_threshold.valueChanged.connect(
            self._update_open_headers
        )

        self.alias_checkbox = QCheckBox(
            "Alias gruplarını birleştir"
        )
        self.alias_checkbox.setChecked(True)

        self.turn_frequency_filter = QCheckBox(
            "Turn 25–40 FQ filtresi"
        )
        self.turn_frequency_filter.setChecked(True)

        self.turn_frequency_target = QDoubleSpinBox()
        self.turn_frequency_target.setRange(0.0, 100.0)
        self.turn_frequency_target.setDecimals(1)
        self.turn_frequency_target.setValue(12.0)
        self.turn_frequency_target.setSingleStep(1.0)
        self.turn_frequency_target.setSuffix(" %")
        self.turn_frequency_target.setToolTip(
            "Turn CBet IP gerçek betleri içinde 25–40% pot sizing hedefi"
        )

        self.turn_frequency_tolerance = QDoubleSpinBox()
        self.turn_frequency_tolerance.setRange(0.0, 50.0)
        self.turn_frequency_tolerance.setDecimals(1)
        self.turn_frequency_tolerance.setValue(2.0)
        self.turn_frequency_tolerance.setSingleStep(0.5)
        self.turn_frequency_tolerance.setPrefix("± ")
        self.turn_frequency_tolerance.setSuffix(" %")
        self.turn_frequency_tolerance.setToolTip(
            "Hedef değerin kabul edilen alt ve üst sapması"
        )
        self.turn_frequency_filter.toggled.connect(
            self._turn_frequency_filter_changed
        )

        self.wwsf_filter = QCheckBox("WWSF filtresi")
        self.wwsf_filter.setChecked(True)

        self.wwsf_target = QDoubleSpinBox()
        self.wwsf_target.setRange(0.0, 100.0)
        self.wwsf_target.setDecimals(1)
        self.wwsf_target.setValue(50.0)
        self.wwsf_target.setSingleStep(1.0)
        self.wwsf_target.setSuffix(" %")
        self.wwsf_target.setToolTip("Aranacak WWSF hedef yüzdesi")

        self.wwsf_tolerance = QDoubleSpinBox()
        self.wwsf_tolerance.setRange(0.0, 50.0)
        self.wwsf_tolerance.setDecimals(1)
        self.wwsf_tolerance.setValue(2.0)
        self.wwsf_tolerance.setSingleStep(0.5)
        self.wwsf_tolerance.setPrefix("± ")
        self.wwsf_tolerance.setSuffix(" %")
        self.wwsf_tolerance.setToolTip(
            "WWSF hedefinin kabul edilen alt ve üst sapması"
        )
        self.wwsf_filter.toggled.connect(
            self._wwsf_filter_changed
        )

        self.reference_combo = QComboBox()
        self.reference_combo.setMinimumWidth(220)
        self.reference_combo.addItem(
            "Opsiyonel — doğrudan filtreli tarama",
            "",
        )

        self.load_button = QPushButton(
            "Filtreli Adayları Tara"
        )
        self.compare_button = QPushButton(
            "Referansla Karşılaştır"
        )

        self.load_button.clicked.connect(
            self.load_entities
        )
        self.compare_button.clicked.connect(
            self.calculate_similarity
        )

        labels = [
            "Site",
            "Stakes",
            "Minimum Hand",
            "Min VPIP (>)",
            "Min PFR (>)",
            "Open Stat Eşiği (>)",
            "Opsiyonel Referans Oyuncu / Alias",
        ]

        widgets = [
            self.site_combo,
            self.stakes_combo,
            self.minimum_hands,
            self.minimum_vpip,
            self.minimum_pfr,
            self.large_open_threshold,
            self.reference_combo,
        ]

        for index, (label, widget) in enumerate(
            zip(labels, widgets)
        ):
            grid.addWidget(QLabel(label), 0, index)
            grid.addWidget(widget, 1, index)

        grid.addWidget(self.alias_checkbox, 2, 0, 1, 2)
        grid.addWidget(self.turn_frequency_filter, 2, 2, 1, 2)
        grid.addWidget(QLabel("Hedef / Tolerans"), 2, 4)
        grid.addWidget(self.turn_frequency_target, 2, 5)
        grid.addWidget(self.turn_frequency_tolerance, 2, 6)
        grid.addWidget(self.wwsf_filter, 3, 2, 1, 2)
        grid.addWidget(QLabel("Hedef / Tolerans"), 3, 4)
        grid.addWidget(self.wwsf_target, 3, 5)
        grid.addWidget(self.wwsf_tolerance, 3, 6)
        grid.addWidget(self.load_button, 4, 0, 1, 4)
        grid.addWidget(self.compare_button, 4, 4, 1, 3)

        root.addWidget(filters)

        cards = QHBoxLayout()
        cards.setSpacing(12)

        self.reference_card = self._card(
            "Referans",
            "—",
        )
        self.reference_hands_card = self._card(
            "Referans Hands",
            "0",
        )
        self.top_match_card = self._card(
            "En Yakın Profil",
            "—",
        )
        self.top_score_card = self._card(
            "En Yüksek Skor",
            "—",
        )

        cards.addWidget(self.reference_card)
        cards.addWidget(self.reference_hands_card)
        cards.addWidget(self.top_match_card)
        cards.addWidget(self.top_score_card)

        root.addLayout(cards)

        self.status_label = QLabel(
            "Filtreleri ayarla ve doğrudan aday taraması başlat."
        )
        self.status_label.setObjectName("PageSubtitle")
        self.status_label.setWordWrap(True)

        root.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(20)
        self.table.setHorizontalHeaderLabels(
            [
                "Oyuncu / Alias",
                "Benzerlik %",
                "Mesafe",
                "Hands",
                "Birleşen Nick",
                "Güven",
                "VPIP",
                "PFR",
                "3Bet",
                "Fold to 3Bet",
                "EP >3.4x %",
                "MP >3.4x %",
                "CO >3.4x %",
                "BTN >3.4x %",
                "SB >3.4x %",
                "Flop CBet",
                "Turn CBet IP 25–40 FQ %",
                "Turn Barrel",
                "River Barrel",
                "WWSF",
            ]
        )
        self._update_open_headers()
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
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )

        for index in range(1, 20):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        root.addWidget(self.table, 1)

        warning = QLabel(
            "Turn CBet IP 25–40 FQ, geçerli pot hesabı bulunan gerçek "
            "Turn CBet IP betleri içindeki 25–40% pot sizing frekansıdır. "
            "Yüksek benzerlik tek başına bot kanıtı değildir."
        )
        warning.setWordWrap(True)
        warning.setObjectName("PageSubtitle")

        root.addWidget(warning)

        self.setStyleSheet(
            """
            QFrame#SimilarityFilters {
                background: #171b24;
                border: 1px solid #303744;
                border-radius: 12px;
            }

            QFrame#SimilarityCard {
                background: #1d222d;
                border: 1px solid #343b49;
                border-radius: 11px;
            }

            QLabel#SimilarityCardTitle {
                color: #9ca3af;
                font-size: 12px;
            }

            QLabel#SimilarityCardValue {
                font-size: 21px;
                font-weight: 800;
            }
            """
        )

    def _update_open_headers(self, _value: float | None = None) -> None:
        if not hasattr(self, "table"):
            return
        threshold = self.large_open_threshold.value()
        for column, position in zip(
            range(10, 15), ("EP", "MP", "CO", "BTN", "SB")
        ):
            item = self.table.horizontalHeaderItem(column)
            if item is not None:
                item.setText(f"{position} >{threshold:.1f}x %")

    def _turn_frequency_filter_changed(self, checked: bool) -> None:
        self.turn_frequency_target.setEnabled(checked)
        self.turn_frequency_tolerance.setEnabled(checked)

    def _turn_frequency_target_value(self) -> float | None:
        if not self.turn_frequency_filter.isChecked():
            return None
        return self.turn_frequency_target.value()

    def _turn_frequency_summary(self) -> str:
        target = self._turn_frequency_target_value()
        if target is None:
            return "Turn 25–40 FQ filtresi kapalı"
        tolerance = self.turn_frequency_tolerance.value()
        lower = max(0.0, target - tolerance)
        upper = min(100.0, target + tolerance)
        exact = " (tam eşleşme)" if tolerance == 0.0 else ""
        return f"Turn 25–40 FQ {lower:.1f}–{upper:.1f}%{exact}"

    def _wwsf_filter_changed(self, checked: bool) -> None:
        self.wwsf_target.setEnabled(checked)
        self.wwsf_tolerance.setEnabled(checked)

    def _wwsf_target_value(self) -> float | None:
        if not self.wwsf_filter.isChecked():
            return None
        return self.wwsf_target.value()

    def _wwsf_summary(self) -> str:
        target = self._wwsf_target_value()
        if target is None:
            return "WWSF filtresi kapalı"
        tolerance = self.wwsf_tolerance.value()
        lower = max(0.0, target - tolerance)
        upper = min(100.0, target + tolerance)
        exact = " (tam eşleşme)" if tolerance == 0.0 else ""
        return f"WWSF {lower:.1f}–{upper:.1f}%{exact}"

    def _card(
        self,
        title: str,
        value: str,
    ) -> QFrame:
        frame = QFrame()
        frame.setObjectName("SimilarityCard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)

        title_label = QLabel(title)
        title_label.setObjectName(
            "SimilarityCardTitle"
        )

        value_label = QLabel(value)
        value_label.setObjectName(
            "SimilarityCardValue"
        )
        value_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        frame.value_label = value_label
        frame.title_label = title_label

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
                "Bot Similarity Filtre Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def load_entities(self) -> None:
        if self.load_thread is not None or self.worker_thread is not None:
            return

        filters: dict[str, Any] = {
            "site": str(self.site_combo.currentData() or ""),
            "stakes": str(self.stakes_combo.currentData() or ""),
            "minimum_hands": self.minimum_hands.value(),
            "minimum_vpip": self.minimum_vpip.value(),
            "minimum_pfr": self.minimum_pfr.value(),
            "large_open_threshold": self.large_open_threshold.value(),
            "turn_size_frequency_target": self._turn_frequency_target_value(),
            "turn_size_frequency_tolerance": (
                self.turn_frequency_tolerance.value()
            ),
            "wwsf_target": self._wwsf_target_value(),
            "wwsf_tolerance": self.wwsf_tolerance.value(),
            "use_aliases": self.alias_checkbox.isChecked(),
            "limit": 5000,
        }

        self.load_button.setEnabled(False)
        self.compare_button.setEnabled(False)
        self.status_label.setText(
            "Filtreli adaylar arka planda hazırlanıyor…"
        )

        self.load_thread = QThread(self)
        self.load_worker = EntityLoadWorker(
            self.database_path,
            filters,
        )
        self.load_worker.moveToThread(self.load_thread)

        self.load_thread.started.connect(self.load_worker.run)
        self.load_worker.finished.connect(self._entities_loaded)
        self.load_worker.failed.connect(self._entity_load_failed)
        self.load_worker.finished.connect(self.load_thread.quit)
        self.load_worker.failed.connect(self.load_thread.quit)
        self.load_thread.finished.connect(self._cleanup_entity_loader)
        self.load_thread.start()

    @Slot(list, dict)
    def _entities_loaded(
        self,
        rows: list[dict[str, Any]],
        diagnostics: dict[str, Any],
    ) -> None:
        self.reference_combo.clear()
        self.reference_combo.addItem(
            "Opsiyonel — doğrudan filtreli tarama",
            "",
        )

        for row in rows:
            label = (
                f"{row['player_name']} "
                f"({row['hands']:,} hands)"
            )
            self.reference_combo.addItem(label, row["player_name"])

        self._populate_table(rows)
        self.reference_card.title_label.setText("Tarama Modu")
        self.reference_card.value_label.setText("Filtreden")
        self.reference_hands_card.title_label.setText("Aday Sayısı")
        self.reference_hands_card.value_label.setText(str(len(rows)))
        self.top_match_card.title_label.setText("En Yüksek Sample")
        self.top_score_card.title_label.setText("Hands")

        if rows:
            self.top_match_card.value_label.setText(rows[0]["player_name"])
            self.top_score_card.value_label.setText(
                f"{int(rows[0]['hands']):,}".replace(",", ".")
            )
        else:
            self.top_match_card.value_label.setText("—")
            self.top_score_card.value_label.setText("—")

        audit = (
            f"Filtre akışı: Temel "
            f"{int(diagnostics.get('basic_candidates') or 0)} → "
            f"Turn {int(diagnostics.get('turn_pass') or 0)} → "
            f"WWSF {int(diagnostics.get('wwsf_pass') or 0)} → "
            f"Sonuç {len(rows)}"
        )
        missing_parts = []
        missing_turn = int(diagnostics.get("missing_turn") or 0)
        missing_wwsf = int(diagnostics.get("missing_wwsf") or 0)
        if missing_turn:
            missing_parts.append(f"Turn samplesiz {missing_turn}")
        if missing_wwsf:
            missing_parts.append(f"WWSF samplesiz {missing_wwsf}")
        missing_text = (
            " • " + " • ".join(missing_parts)
            if missing_parts else ""
        )

        self.status_label.setText(
            f"{audit}{missing_text}\n"
            f"Hands ≥{self.minimum_hands.value():,} • "
            f"VPIP >{self.minimum_vpip.value():.1f}% • "
            f"PFR >{self.minimum_pfr.value():.1f}% • "
            f"Open stat eşiği >{self.large_open_threshold.value():.1f}x • "
            f"{self._turn_frequency_summary()} • "
            f"{self._wwsf_summary()}"
        )

    @Slot(str)
    def _entity_load_failed(self, message: str) -> None:
        QMessageBox.critical(
            self,
            "Aday Tarama Hatası",
            message,
        )
        self.status_label.setText("Filtreli adaylar yüklenemedi.")

    def _cleanup_entity_loader(self) -> None:
        self.load_worker = None
        self.load_thread = None
        self.load_button.setEnabled(True)
        self.compare_button.setEnabled(True)

    def calculate_similarity(self) -> None:
        if self.worker_thread is not None or self.load_thread is not None:
            return

        reference_name = str(
            self.reference_combo.currentData() or ""
        )

        if not reference_name:
            self.load_entities()
            return

        self.compare_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self.status_label.setText(
            "Benzerlik profilleri hesaplanıyor…"
        )

        self.worker_thread = QThread(self)
        self.worker = SimilarityWorker(
            database_path=self.database_path,
            reference_name=reference_name,
            site=str(
                self.site_combo.currentData() or ""
            ),
            stakes=str(
                self.stakes_combo.currentData() or ""
            ),
            minimum_hands=self.minimum_hands.value(),
            minimum_vpip=self.minimum_vpip.value(),
            minimum_pfr=self.minimum_pfr.value(),
            large_open_threshold=self.large_open_threshold.value(),
            turn_size_frequency_target=(
                self._turn_frequency_target_value()
            ),
            turn_size_frequency_tolerance=(
                self.turn_frequency_tolerance.value()
            ),
            wwsf_target=self._wwsf_target_value(),
            wwsf_tolerance=self.wwsf_tolerance.value(),
            use_aliases=self.alias_checkbox.isChecked(),
        )

        self.worker.moveToThread(
            self.worker_thread
        )

        self.worker_thread.started.connect(
            self.worker.run
        )
        self.worker.finished.connect(
            self._similarity_finished
        )
        self.worker.failed.connect(
            self._similarity_failed
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

    @Slot(dict, list)
    def _similarity_finished(
        self,
        reference: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> None:
        self._populate_table(rows)

        self.reference_card.title_label.setText("Referans")
        self.reference_hands_card.title_label.setText("Referans Hands")
        self.top_match_card.title_label.setText("En Yakın Profil")
        self.top_score_card.title_label.setText("En Yüksek Skor")
        self.reference_card.value_label.setText(
            reference["player_name"]
        )
        self.reference_hands_card.value_label.setText(
            f"{int(reference['hands']):,}".replace(",", ".")
        )

        if rows:
            self.top_match_card.value_label.setText(
                rows[0]["player_name"]
            )
            self.top_score_card.value_label.setText(
                f"{rows[0]['similarity']:.2f}%"
            )
        else:
            self.top_match_card.value_label.setText("—")
            self.top_score_card.value_label.setText("—")

        self.status_label.setText(
            f"{len(rows)} profil karşılaştırıldı."
        )

    def _populate_table(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(rows))

        for row_index, row in enumerate(rows):
            values = [
                row["player_name"],
                self._stat_text(row.get("similarity")),
                self._stat_text(row.get("distance")),
                str(row["hands"]),
                str(row["merged_nicks"]),
                str(row.get("confidence") or "—"),
                f"{row['vpip']:.2f}",
                f"{row['pfr']:.2f}",
                f"{row['three_bet']:.2f}",
                self._stat_text(row.get("fold_to_3bet")),
                self._stat_text(row.get("ep_open_gt_34")),
                self._stat_text(row.get("mp_open_gt_34")),
                self._stat_text(row.get("co_open_gt_34")),
                self._stat_text(row.get("btn_open_gt_34")),
                self._stat_text(row.get("sb_open_gt_34")),
                self._stat_text(row["flop_cbet"]),
                self._stat_text(row.get("turn_cbet_ip_size_25_40")),
                self._stat_text(row["turn_barrel"]),
                self._stat_text(row["river_barrel"]),
                self._stat_text(row.get("wwsf")),
            ]
            numeric_values = [
                None,
                row.get("similarity"), row.get("distance"), row.get("hands"),
                row.get("merged_nicks"), None,
                row.get("vpip"), row.get("pfr"), row.get("three_bet"),
                row.get("fold_to_3bet"),
                row.get("ep_open_gt_34"), row.get("mp_open_gt_34"),
                row.get("co_open_gt_34"), row.get("btn_open_gt_34"),
                row.get("sb_open_gt_34"), row.get("flop_cbet"),
                row.get("turn_cbet_ip_size_25_40"), row.get("turn_barrel"),
                row.get("river_barrel"), row.get("wwsf"),
            ]

            for column_index, value in enumerate(values):
                numeric_value = numeric_values[column_index]
                item = (
                    NumericTableItem(str(value), float(numeric_value))
                    if numeric_value is not None
                    else QTableWidgetItem(str(value))
                )

                if column_index > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )

                sample_keys = {
                    9: "fold_to_3bet_opp",
                    10: "ep_open_gt_34_opp",
                    11: "mp_open_gt_34_opp",
                    12: "co_open_gt_34_opp",
                    13: "btn_open_gt_34_opp",
                    14: "sb_open_gt_34_opp",
                    16: "turn_cbet_ip_size_25_40_sample",
                    19: "wwsf_opp",
                }
                sample_key = sample_keys.get(column_index)
                if sample_key:
                    item.setToolTip(
                        f"Opportunity sample: {int(row.get(sample_key) or 0):,}"
                    )

                self.table.setItem(
                    row_index,
                    column_index,
                    item,
                )

        self.table.setSortingEnabled(True)
        self.table.setUpdatesEnabled(True)

    def _stat_text(
        self,
        value: float | None,
    ) -> str:
        if value is None:
            return "—"

        return f"{value:.2f}"

    @Slot(str)
    def _similarity_failed(
        self,
        message: str,
    ) -> None:
        QMessageBox.critical(
            self,
            "Bot Similarity Hatası",
            message,
        )
        self.status_label.setText(
            "Benzerlik hesaplanamadı."
        )

    def _cleanup_worker(self) -> None:
        self.compare_button.setEnabled(True)
        self.load_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
