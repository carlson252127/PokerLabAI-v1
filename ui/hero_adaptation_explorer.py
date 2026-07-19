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
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.hero_adaptation_service import (
    HeroAdaptationService,
)


class HeroAdaptationWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        main_database_path: str,
        **kwargs: Any,
    ) -> None:
        super().__init__()

        self.service = HeroAdaptationService(
            main_database_path
        )
        self.kwargs = kwargs

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(
                self.service.analyze(
                    **self.kwargs
                )
            )
        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: "
                f"{exc}"
            )


class HeroAdaptationExplorer(QWidget):
    COLUMNS = [
        ("block_label", "5K Blok"),
        ("hero_hands", "Hero Hands"),
        ("opens", "Open"),
        ("open_frequency", "Open %"),
        ("avg_open_size", "Ort. Size"),

        ("pool_fold", "Pool Fold"),
        ("delta_pool_fold", "Δ Fold"),
        ("pool_call", "Pool Call"),
        ("pool_3bet", "Pool 3Bet"),
        ("delta_pool_3bet", "Δ 3Bet"),

        ("fold_to_3bet", "Hero F3B"),
        ("delta_fold_to_3bet", "Δ Hero F3B"),
        ("f3b_sample", "F3B Smp"),

        ("flop_cbet", "Flop CBet"),
        ("delta_flop_cbet", "Δ FCB"),
        ("flop_sample", "FCB Smp"),

        ("turn_barrel", "Turn Barrel"),
        ("delta_turn_barrel", "Δ TB"),
        ("turn_sample", "TB Smp"),

        ("river_barrel", "River Barrel"),
        ("delta_river_barrel", "Δ RB"),
        ("river_sample", "RB Smp"),

        ("wwsf", "WWSF"),
        ("delta_wwsf", "Δ WWSF"),
        ("wtsd", "WTSD"),
        ("wsd", "W$SD"),
        ("delta_wsd", "Δ W$SD"),
        ("wsd_sample", "W$SD Smp"),
        ("confidence", "Güven"),
    ]

    def __init__(
        self,
        main_database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.main_database_path = (
            main_database_path
        )
        self.service = HeroAdaptationService(
            main_database_path
        )
        self.worker_thread: QThread | None = None
        self.worker: (
            HeroAdaptationWorker
            | None
        ) = None

        self._build_ui()

        QTimer.singleShot(
            100,
            self.refresh_experiments,
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

        title = QLabel(
            "Hero Adaptation Analyzer v1"
        )
        title.setObjectName(
            "PageTitle"
        )

        subtitle = QLabel(
            "Experiment database içindeki Hero stratejisini "
            "ve poolun 5K bloklarda verdiği tepkiyi birlikte ölçer."
        )
        subtitle.setObjectName(
            "PageSubtitle"
        )

        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName(
            "HeroAdaptationFilters"
        )
        grid = QGridLayout(filters)
        grid.setContentsMargins(
            15,
            15,
            15,
            15,
        )

        self.experiment_combo = QComboBox()
        self.experiment_combo.setMinimumWidth(
            320
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

        self.size_combo = QComboBox()

        for label, value in [
            ("Tüm Sizelar", ""),
            ("≤2.0x", "≤2.0x"),
            ("2.1–2.3x", "2.1–2.3x"),
            ("2.4–2.6x", "2.4–2.6x"),
            ("2.7–3.1x", "2.7–3.1x"),
            (">3.1x", ">3.1x"),
        ]:
            self.size_combo.addItem(
                label,
                value,
            )

        labels = [
            "Experiment",
            "Pozisyon",
            "Open Size",
        ]
        widgets = [
            self.experiment_combo,
            self.position_combo,
            self.size_combo,
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

        self.refresh_button = QPushButton(
            "Experiment Listesini Yenile"
        )
        self.analyze_button = QPushButton(
            "Hero Adaptasyonunu Analiz Et"
        )

        self.refresh_button.clicked.connect(
            self.refresh_experiments
        )
        self.analyze_button.clicked.connect(
            self.run_analysis
        )

        buttons = QHBoxLayout()
        buttons.addWidget(
            self.refresh_button
        )
        buttons.addWidget(
            self.analyze_button
        )
        buttons.addStretch()

        grid.addLayout(
            buttons,
            2,
            0,
            1,
            3,
        )

        root.addWidget(filters)

        cards = QHBoxLayout()

        self.hands_card = self._card(
            "Hero Hands",
            "0",
        )
        self.blocks_card = self._card(
            "5K Blok",
            "0",
        )
        self.adaptation_card = self._card(
            "Adaptation",
            "0",
        )
        self.drift_card = self._card(
            "Hero Drift",
            "0",
        )
        self.fold_card = self._card(
            "Pool Fold Trend",
            "+0.0",
        )
        self.threebet_card = self._card(
            "Pool 3Bet Trend",
            "+0.0",
        )
        self.status_card = self._card(
            "Status",
            "—",
        )

        for card in (
            self.hands_card,
            self.blocks_card,
            self.adaptation_card,
            self.drift_card,
            self.fold_card,
            self.threebet_card,
            self.status_card,
        ):
            cards.addWidget(card)

        root.addLayout(cards)

        self.summary_label = QLabel(
            "Experiment seçip analizi başlat."
        )
        self.summary_label.setObjectName(
            "HeroAdaptationSummary"
        )
        self.summary_label.setWordWrap(
            True
        )
        root.addWidget(
            self.summary_label
        )

        body = QHBoxLayout()

        self.table = QTableWidget()
        self.table.setColumnCount(
            len(self.COLUMNS)
        )
        self.table.setHorizontalHeaderLabels(
            [
                label
                for _key, label
                in self.COLUMNS
            ]
        )
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.table.setAlternatingRowColors(
            True
        )
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.verticalHeader().setVisible(
            False
        )

        header = self.table.horizontalHeader()

        for index in range(
            len(self.COLUMNS)
        ):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMinimumWidth(
            390
        )

        body.addWidget(
            self.table,
            4,
        )
        body.addWidget(
            self.notes,
            1,
        )

        root.addLayout(
            body,
            1,
        )

        self.status_label = QLabel("")
        self.status_label.setObjectName(
            "PageSubtitle"
        )
        root.addWidget(
            self.status_label
        )

        self.setStyleSheet(
            """
            QFrame#HeroAdaptationFilters {
                background:#171b24;
                border:1px solid #303744;
                border-radius:12px;
            }

            QFrame#HeroAdaptationCard {
                background:#1d222d;
                border:1px solid #343b49;
                border-radius:11px;
            }

            QLabel#HeroAdaptationCardTitle {
                color:#9ca3af;
                font-size:12px;
            }

            QLabel#HeroAdaptationCardValue {
                font-size:18px;
                font-weight:800;
            }

            QLabel#HeroAdaptationSummary {
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
        frame.setObjectName(
            "HeroAdaptationCard"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            13,
            10,
            13,
            10,
        )

        title_label = QLabel(title)
        title_label.setObjectName(
            "HeroAdaptationCardTitle"
        )

        value_label = QLabel(value)
        value_label.setObjectName(
            "HeroAdaptationCardValue"
        )
        value_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        value_label.setWordWrap(True)

        frame.value_label = value_label

        layout.addWidget(title_label)
        layout.addWidget(value_label)

        return frame

    def refresh_experiments(
        self,
    ) -> None:
        current = (
            self.experiment_combo.currentData()
        )
        records = (
            self.service.list_experiments()
        )

        self.experiment_combo.clear()

        for record in records:
            self.experiment_combo.addItem(
                (
                    f"{record['name']} — "
                    f"{record['hero_name']} — "
                    f"{record['block_size']:,}"
                ),
                record["name"],
            )

        index = (
            self.experiment_combo.findData(
                current
            )
        )

        if index >= 0:
            self.experiment_combo.setCurrentIndex(
                index
            )

        self.status_label.setText(
            f"{len(records)} experiment yüklendi."
        )

    def run_analysis(self) -> None:
        if self.worker_thread is not None:
            return

        experiment_name = str(
            self.experiment_combo.currentData()
            or ""
        )

        if not experiment_name:
            QMessageBox.information(
                self,
                "Hero Adaptation Analyzer",
                "Önce experiment oluştur veya seç.",
            )
            return

        self.refresh_button.setEnabled(
            False
        )
        self.analyze_button.setEnabled(
            False
        )
        self.status_label.setText(
            "Hero ve pool 5K blokları hesaplanıyor…"
        )

        self.worker_thread = QThread(
            self
        )
        self.worker = HeroAdaptationWorker(
            self.main_database_path,
            experiment_name=experiment_name,
            position=str(
                self.position_combo.currentData()
                or ""
            ),
            size_bucket=str(
                self.size_combo.currentData()
                or ""
            ),
            minimum_open_sample=20,
            minimum_postflop_sample=10,
        )

        self.worker.moveToThread(
            self.worker_thread
        )
        self.worker_thread.started.connect(
            self.worker.run
        )
        self.worker.finished.connect(
            self._finished
        )
        self.worker.failed.connect(
            self._failed
        )
        self.worker.finished.connect(
            self.worker_thread.quit
        )
        self.worker.failed.connect(
            self.worker_thread.quit
        )
        self.worker_thread.finished.connect(
            self._cleanup
        )
        self.worker_thread.start()

    @Slot(dict)
    def _finished(
        self,
        report: dict[str, Any],
    ) -> None:
        blocks = report.get(
            "blocks",
            [],
        )
        pool_trend = report.get(
            "pool_trend",
            {},
        )

        self.hands_card.value_label.setText(
            f"{int(report.get('hero_hands', 0)):,}"
            .replace(",", ".")
        )
        self.blocks_card.value_label.setText(
            str(
                int(
                    report.get(
                        "total_blocks",
                        0,
                    )
                )
            )
        )
        self.adaptation_card.value_label.setText(
            f"{float(report.get('adaptation_score', 0)):.0f}"
        )
        self.drift_card.value_label.setText(
            f"{float(report.get('drift_score', 0)):.0f}"
        )
        self.fold_card.value_label.setText(
            f"{float(pool_trend.get('pool_fold', 0)):+.1f}"
        )
        self.threebet_card.value_label.setText(
            f"{float(pool_trend.get('pool_3bet', 0)):+.1f}"
        )
        self.status_card.value_label.setText(
            str(
                report.get(
                    "status",
                    "—",
                )
            )
        )
        self.summary_label.setText(
            str(
                report.get(
                    "summary",
                    "",
                )
            )
        )

        self._fill_table(blocks)

        recommendations = report.get(
            "recommendations",
            [],
        )

        text = [
            "AI COACH — ADAPTATION",
            "=" * 32,
        ]

        for index, note in enumerate(
            recommendations,
            start=1,
        ):
            text.append(
                f"{index}. {note}"
            )

        self.notes.setPlainText(
            "\n".join(text)
        )
        self.status_label.setText(
            f"{len(blocks)} blok analiz edildi."
        )

    def _fill_table(
        self,
        blocks: list[dict[str, Any]],
    ) -> None:
        self.table.setUpdatesEnabled(
            False
        )
        self.table.clearContents()
        self.table.setRowCount(
            len(blocks)
        )

        percent_keys = {
            "open_frequency",
            "pool_fold",
            "delta_pool_fold",
            "pool_call",
            "pool_3bet",
            "delta_pool_3bet",
            "fold_to_3bet",
            "delta_fold_to_3bet",
            "flop_cbet",
            "delta_flop_cbet",
            "turn_barrel",
            "delta_turn_barrel",
            "river_barrel",
            "delta_river_barrel",
            "wwsf",
            "delta_wwsf",
            "wtsd",
            "wsd",
            "delta_wsd",
        }

        integer_keys = {
            "hero_hands",
            "opens",
            "f3b_sample",
            "flop_sample",
            "turn_sample",
            "river_sample",
            "wsd_sample",
        }

        for row_index, row in enumerate(
            blocks
        ):
            for column_index, (
                key,
                _label,
            ) in enumerate(
                self.COLUMNS
            ):
                value = row.get(
                    key,
                    "",
                )

                if key == "avg_open_size":
                    display = (
                        f"{float(value or 0):.2f}x"
                    )
                elif key in percent_keys:
                    if key.startswith(
                        "delta_"
                    ):
                        display = (
                            f"{float(value or 0):+.2f}"
                        )
                    else:
                        display = (
                            f"{float(value or 0):.2f}"
                        )
                elif key in integer_keys:
                    display = str(
                        int(value or 0)
                    )
                else:
                    display = str(value)

                item = QTableWidgetItem(
                    display
                )

                if key not in {
                    "block_label",
                    "confidence",
                }:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignCenter
                    )

                self.table.setItem(
                    row_index,
                    column_index,
                    item,
                )

        self.table.setUpdatesEnabled(
            True
        )

    @Slot(str)
    def _failed(
        self,
        message: str,
    ) -> None:
        QMessageBox.critical(
            self,
            "Hero Adaptation Hatası",
            message,
        )
        self.status_label.setText(
            "Analiz başarısız."
        )

    def _cleanup(self) -> None:
        self.refresh_button.setEnabled(
            True
        )
        self.analyze_button.setEnabled(
            True
        )
        self.worker = None
        self.worker_thread = None
