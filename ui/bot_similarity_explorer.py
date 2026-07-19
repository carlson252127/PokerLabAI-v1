from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QCheckBox,
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

from services.bot_similarity_service import (
    BotSimilarityService,
)


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
        use_aliases: bool,
    ) -> None:
        super().__init__()

        self.service = BotSimilarityService(database_path)
        self.reference_name = reference_name
        self.site = site
        self.stakes = stakes
        self.minimum_hands = minimum_hands
        self.use_aliases = use_aliases

    @Slot()
    def run(self) -> None:
        try:
            reference, rows = self.service.compare(
                reference_name=self.reference_name,
                site=self.site,
                stakes=self.stakes,
                minimum_hands=self.minimum_hands,
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
        self.filters_loaded = False

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Bot Similarity")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Oyuncu ve alias profillerini temel istatistiklere göre "
            "karşılaştırır. Yüksek skor kesin bot kanıtı değildir."
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
        self.minimum_hands.setValue(500)
        self.minimum_hands.setSingleStep(500)

        self.alias_checkbox = QCheckBox(
            "Alias gruplarını birleştir"
        )
        self.alias_checkbox.setChecked(True)

        self.reference_combo = QComboBox()
        self.reference_combo.setMinimumWidth(220)

        self.load_button = QPushButton(
            "Referans Listesini Yükle"
        )
        self.compare_button = QPushButton(
            "Benzerlik Hesapla"
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
            "Referans Oyuncu / Alias",
        ]

        widgets = [
            self.site_combo,
            self.stakes_combo,
            self.minimum_hands,
            self.reference_combo,
        ]

        for index, (label, widget) in enumerate(
            zip(labels, widgets)
        ):
            grid.addWidget(QLabel(label), 0, index)
            grid.addWidget(widget, 1, index)

        grid.addWidget(self.alias_checkbox, 1, 4)
        grid.addWidget(self.load_button, 1, 5)
        grid.addWidget(self.compare_button, 1, 6)

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
            "Önce referans listesini yükle."
        )
        self.status_label.setObjectName("PageSubtitle")

        root.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(12)
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
                "Flop CBet",
                "Turn Barrel",
                "River Barrel",
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
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )

        for index in range(1, 12):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        root.addWidget(self.table, 1)

        warning = QLabel(
            "Benzerlik skoru yalnızca seçili istatistik profilini "
            "karşılaştırır. Aynı stratejiye işaret edebilir fakat tek "
            "başına otomasyon veya bot kanıtı değildir."
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
        try:
            rows = self.service.get_entities(
                site=str(
                    self.site_combo.currentData() or ""
                ),
                stakes=str(
                    self.stakes_combo.currentData() or ""
                ),
                minimum_hands=self.minimum_hands.value(),
                use_aliases=self.alias_checkbox.isChecked(),
                limit=5000,
            )

            self.reference_combo.clear()

            for row in rows:
                label = (
                    f"{row['player_name']} "
                    f"({row['hands']:,} hands)"
                )
                self.reference_combo.addItem(
                    label,
                    row["player_name"],
                )

            self.status_label.setText(
                f"{len(rows)} referans profil yüklendi."
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Referans Yükleme Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def calculate_similarity(self) -> None:
        if self.worker_thread is not None:
            return

        reference_name = str(
            self.reference_combo.currentData() or ""
        )

        if not reference_name:
            QMessageBox.information(
                self,
                "Bot Similarity",
                "Önce referans listesini yükleyip oyuncu seç.",
            )
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
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(rows))

        for row_index, row in enumerate(rows):
            values = [
                row["player_name"],
                f"{row['similarity']:.2f}",
                f"{row['distance']:.2f}",
                str(row["hands"]),
                str(row["merged_nicks"]),
                row["confidence"],
                f"{row['vpip']:.2f}",
                f"{row['pfr']:.2f}",
                f"{row['three_bet']:.2f}",
                self._stat_text(row["flop_cbet"]),
                self._stat_text(row["turn_barrel"]),
                self._stat_text(row["river_barrel"]),
            ]

            for column_index, value in enumerate(values):
                item = QTableWidgetItem(str(value))

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
