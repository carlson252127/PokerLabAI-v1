from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from services.size_board_strategy_service import SizeBoardStrategyService


SUIT_SYMBOLS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
RED_SUITS = {"h", "d"}


class SizeBoardWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, database_path: str, args: dict[str, Any]) -> None:
        super().__init__()
        self.service = SizeBoardStrategyService(database_path)
        self.args = args

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.service.analyze(**self.args))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class PokerCard(QFrame):
    def __init__(self, card: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PokerCard")
        self.setFixedSize(52, 70)

        match = re.fullmatch(r"([2-9TJQKA])([shdc])", card, re.I)
        rank, suit = match.groups() if match else ("?", "s")
        suit = suit.lower()
        color = "#d92d3f" if suit in RED_SUITS else "#111827"

        self.setStyleSheet(
            f"""
            QFrame#PokerCard {{
                background:#f8fafc;
                border:1px solid #cbd5e1;
                border-radius:7px;
            }}
            QFrame#PokerCard QLabel {{
                background:transparent;
                border:none;
                color:{color};
            }}
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 2, 3, 2)
        layout.setSpacing(0)

        rank_label = QLabel(rank.upper())
        rank_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rank_label.setStyleSheet(
            f"font-size:23px;font-weight:900;color:{color};"
        )
        suit_label = QLabel(SUIT_SYMBOLS.get(suit, "?"))
        suit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        suit_label.setStyleSheet(
            f"font-size:25px;font-weight:800;color:{color};"
        )
        layout.addWidget(rank_label)
        layout.addWidget(suit_label)


class MetricBox(QFrame):
    def __init__(
        self,
        title: str,
        value: str,
        subtitle: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("MetricBox")
        self.setMinimumWidth(105)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setObjectName("MetricTitle")
        value_label = QLabel(value)
        value_label.setObjectName("MetricValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        layout.addWidget(value_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setObjectName("MetricSub")
            subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(subtitle_label)


class BoardResearchCard(QFrame):
    selected = Signal(dict)

    def __init__(self, row: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.row = row
        self.setObjectName("BoardResearchCard")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(142)

        root = QHBoxLayout(self)
        root.setContentsMargins(15, 13, 15, 13)
        root.setSpacing(14)

        identity = QVBoxLayout()
        identity.setSpacing(4)
        family = QLabel(str(row.get("texture") or "Unknown"))
        family.setObjectName("BoardFamily")
        meta = QLabel(
            f"{row.get('position', '—')}  •  "
            f"{row.get('size_bucket', '—')}"
        )
        meta.setObjectName("BoardMeta")
        hands = QLabel(f"{int(row.get('hands') or 0):,} el")
        hands.setObjectName("BoardHands")
        identity.addWidget(family)
        identity.addWidget(meta)
        identity.addWidget(hands)
        identity.addStretch()
        root.addLayout(identity, 2)

        board_box = QVBoxLayout()
        board_box.setSpacing(5)
        cards_row = QHBoxLayout()
        cards_row.setSpacing(5)
        board = str(row.get("representative_board") or "")
        cards = board.split()
        if len(cards) == 3:
            for card in cards:
                cards_row.addWidget(PokerCard(card))
        else:
            no_board = QLabel("Board yok")
            no_board.setObjectName("BoardMeta")
            cards_row.addWidget(no_board)
        board_box.addLayout(cards_row)
        rep_count = int(row.get("representative_board_hands") or 0)
        board_caption = QLabel(
            f"{board or '—'}  •  temsilî {rep_count:,} el"
        )
        board_caption.setObjectName("BoardCaption")
        board_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        board_box.addWidget(board_caption)
        root.addLayout(board_box, 2)

        root.addWidget(
            MetricBox(
                "Flop",
                f"{float(row.get('flop_cbet') or 0):.1f}%",
                f"avg {float(row.get('flop_avg_bet_pct') or 0):.1f}%",
            )
        )
        root.addWidget(
            MetricBox(
                "Turn",
                f"{float(row.get('turn_barrel') or 0):.1f}%",
                f"avg {float(row.get('turn_avg_bet_pct') or 0):.1f}%",
            )
        )
        root.addWidget(
            MetricBox(
                "River",
                f"{float(row.get('river_barrel') or 0):.1f}%",
                f"avg {float(row.get('river_avg_bet_pct') or 0):.1f}%",
            )
        )
        root.addWidget(MetricBox("WWSF", f"{float(row.get('wwsf') or 0):.1f}%"))
        root.addWidget(MetricBox("W$SD", f"{float(row.get('wsd') or 0):.1f}%"))

        score = float(row.get("difference_score") or 0)
        score_box = MetricBox("Exploit", f"{score:.0f}", str(row.get("confidence") or "—"))
        score_box.setProperty("scoreLevel", "high" if score >= 40 else "mid" if score >= 20 else "low")
        root.addWidget(score_box)

        detail = QPushButton("Detay")
        detail.setObjectName("CardDetailButton")
        detail.setFixedWidth(74)
        detail.clicked.connect(lambda: self.selected.emit(self.row))
        root.addWidget(detail)

        tooltip = (
            f"Size DNA: {row.get('size_dna', '—')}\n"
            f"Öneri: {row.get('interpretation', '—')}"
        )
        self.setToolTip(tooltip)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self.row)
        super().mousePressEvent(event)


class SizeBoardStrategyExplorer(QWidget):
    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.database_path = database_path
        self.service = SizeBoardStrategyService(database_path)
        self.worker_thread: QThread | None = None
        self.worker: SizeBoardWorker | None = None
        self._all_rows: list[dict[str, Any]] = []
        self._build_ui()
        QTimer.singleShot(100, self.refresh_filters)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(11)

        title = QLabel("Size × Board Research Lab")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Open size × board ailesi sonuçlarını gerçek temsilî kartlarla gösterir."
        )
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName("ResearchFilters")
        grid = QGridLayout(filters)
        grid.setContentsMargins(14, 14, 14, 14)

        self.mode_combo = QComboBox()
        for label, value in [
            ("Player", "PLAYER"),
            ("Alias Group", "ALIAS"),
            ("Bot Group", "BOT_GROUP"),
            ("Bot Family", "BOT_FAMILY"),
            ("Human Pool (Botlar Hariç)", "POOL"),
            ("All Pool", "ALL_POOL"),
        ]:
            self.mode_combo.addItem(label, value)

        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumWidth(220)
        self.view_combo = QComboBox()
        self.view_combo.addItem("Basit Çalışma Modu", "STUDY")
        self.view_combo.addItem("Detaylı Araştırma", "DETAIL")
        self.street_combo = QComboBox()
        self.street_combo.addItem("Flop Grupları", "FLOP")
        self.street_combo.addItem("Turn Geçişleri", "TURN")
        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")
        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")
        self.position_combo = QComboBox()
        for label, value in [
            ("Tüm Pozisyonlar", ""), ("UTG", "UTG"),
            ("UTG+1", "UTG+1"), ("HJ", "HJ"), ("CO", "CO"),
            ("BTN", "BTN"), ("SB", "SB"), ("BB", "BB"),
        ]:
            self.position_combo.addItem(label, value)
        self.texture_combo = QComboBox()
        self.texture_combo.addItem("Tüm Gruplar", "")
        self.turn_combo = QComboBox()
        self.turn_combo.addItem("Tüm Turn Tipleri", "")
        for turn_type in [
            "Blank", "Overcard", "Board Pair", "Flush Draw Added",
            "Flush Completed", "Straight Draw Added", "Straight Completed",
            "Combo Dynamic", "No Turn",
        ]:
            self.turn_combo.addItem(turn_type, turn_type)
        self.minimum_sample = QSpinBox()
        self.minimum_sample.setRange(5, 1_000_000)
        self.minimum_sample.setValue(30)
        self.minimum_sample.setSingleStep(10)

        controls = [
            ("Mod", self.mode_combo), ("Kaynak", self.entity_combo),
            ("Görünüm", self.view_combo), ("Street", self.street_combo),
            ("Site", self.site_combo), ("Stakes", self.stakes_combo),
            ("Pozisyon", self.position_combo), ("Grup", self.texture_combo),
            ("Turn Tipi", self.turn_combo), ("Min Sample", self.minimum_sample),
        ]
        for index, (label, widget) in enumerate(controls):
            row = 0 if index < 5 else 2
            column = index % 5
            grid.addWidget(QLabel(label), row, column)
            grid.addWidget(widget, row + 1, column)

        self.load_button = QPushButton("Profilleri Yükle")
        self.analyze_button = QPushButton("Araştırmayı Çalıştır")
        self.analyze_button.setObjectName("PrimaryButton")
        self.load_button.clicked.connect(self.load_entities)
        self.analyze_button.clicked.connect(self.run_analysis)
        self.view_combo.currentIndexChanged.connect(self.refresh_filters)
        self.street_combo.currentIndexChanged.connect(self._street_changed)
        self.mode_combo.currentIndexChanged.connect(self.load_entities)

        buttons = QHBoxLayout()
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.analyze_button)
        buttons.addStretch()
        grid.addLayout(buttons, 4, 0, 1, 5)
        root.addWidget(filters)

        summary_cards = QHBoxLayout()
        self.groups_card = self._summary_card("Gösterilen Grup", "0")
        self.actionable_card = self._summary_card("Çalışılabilir Grup", "0")
        self.strongest_card = self._summary_card("En Güçlü Ayrışma", "—")
        self.score_card = self._summary_card("Exploit Score", "0")
        self.confidence_card = self._summary_card("Güven", "—")
        for card in [
            self.groups_card, self.actionable_card, self.strongest_card,
            self.score_card, self.confidence_card,
        ]:
            summary_cards.addWidget(card)
        root.addLayout(summary_cards)

        self.summary_label = QLabel("Profil seçip araştırmayı başlat.")
        self.summary_label.setObjectName("ResearchSummary")
        self.summary_label.setWordWrap(True)
        self.evidence_label = QLabel("")
        self.evidence_label.setObjectName("ResearchSummary")
        self.evidence_label.setWordWrap(True)
        self.status_label = QLabel("")
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.summary_label)
        root.addWidget(self.evidence_label)
        root.addWidget(self.status_label)

        result_filters = QFrame()
        result_filters.setObjectName("ResultFilters")
        result_grid = QGridLayout(result_filters)
        result_grid.setContentsMargins(12, 10, 12, 10)
        result_grid.setHorizontalSpacing(10)

        self.result_texture_combo = QComboBox()
        self.result_texture_combo.addItem("Tüm Board Tipleri", "")
        self.result_sort_combo = QComboBox()
        for label, value in [
            ("En Çok El", "HANDS"),
            ("En Yüksek Exploit", "EXPLOIT"),
            ("En Yüksek Flop Cbet", "FLOP"),
            ("En Yüksek Turn Barrel", "TURN"),
            ("En Yüksek River Barrel", "RIVER"),
            ("En Yüksek WWSF", "WWSF"),
            ("En Yüksek W$SD", "WSD"),
        ]:
            self.result_sort_combo.addItem(label, value)
        self.result_limit_combo = QComboBox()
        for label, value in [("İlk 10", 10), ("İlk 25", 25), ("İlk 50", 50), ("Tümü", 0)]:
            self.result_limit_combo.addItem(label, value)
        self.result_limit_combo.setCurrentIndex(1)

        self.most_common_label = QLabel("En çok board tipi: —")
        self.most_common_label.setObjectName("MostCommonBoard")

        result_grid.addWidget(QLabel("Board Tipi"), 0, 0)
        result_grid.addWidget(QLabel("Sırala"), 0, 1)
        result_grid.addWidget(QLabel("Göster"), 0, 2)
        result_grid.addWidget(self.result_texture_combo, 1, 0)
        result_grid.addWidget(self.result_sort_combo, 1, 1)
        result_grid.addWidget(self.result_limit_combo, 1, 2)
        result_grid.addWidget(self.most_common_label, 1, 3)
        result_grid.setColumnStretch(3, 1)

        self.result_texture_combo.currentIndexChanged.connect(self._apply_result_filters)
        self.result_sort_combo.currentIndexChanged.connect(self._apply_result_filters)
        self.result_limit_combo.currentIndexChanged.connect(self._apply_result_filters)
        root.addWidget(result_filters)

        content = QHBoxLayout()
        content.setSpacing(10)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("BoardCardScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.card_container = QWidget()
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(0, 0, 4, 0)
        self.card_layout.setSpacing(9)
        self.card_layout.addStretch()
        self.scroll.setWidget(self.card_container)
        content.addWidget(self.scroll, 5)

        self.detail_panel = QFrame()
        self.detail_panel.setObjectName("DetailPanel")
        self.detail_panel.setMinimumWidth(285)
        self.detail_panel.setMaximumWidth(340)
        detail_layout = QVBoxLayout(self.detail_panel)
        detail_layout.setContentsMargins(15, 15, 15, 15)
        self.detail_title = QLabel("Board Detayı")
        self.detail_title.setObjectName("DetailTitle")
        self.detail_board = QWidget()
        self.detail_board_layout = QHBoxLayout(self.detail_board)
        self.detail_board_layout.setContentsMargins(0, 8, 0, 8)
        self.detail_board_layout.setSpacing(7)
        self.detail_family = QLabel("Bir araştırma kartı seç.")
        self.detail_family.setObjectName("BoardFamily")
        self.detail_family.setWordWrap(True)
        self.detail_metrics = QLabel("")
        self.detail_metrics.setObjectName("DetailText")
        self.detail_metrics.setWordWrap(True)
        self.detail_representatives = QLabel("")
        self.detail_representatives.setObjectName("DetailText")
        self.detail_representatives.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_board)
        detail_layout.addWidget(self.detail_family)
        detail_layout.addWidget(self.detail_metrics)
        detail_layout.addWidget(self.detail_representatives)
        detail_layout.addStretch()
        content.addWidget(self.detail_panel, 2)
        root.addLayout(content, 1)

        warning = QLabel(
            "Her kart bir pozisyon × open size × board ailesi grubudur. "
            "Kartların üzerindeki flop, o grupta en sık görülen gerçek boarddur."
        )
        warning.setObjectName("PageSubtitle")
        root.addWidget(warning)

        self.setStyleSheet(
            """
            QFrame#ResearchFilters,QFrame#ResearchCard,QFrame#DetailPanel,QFrame#ResultFilters{
                background:#151b26;border:1px solid #2b3547;border-radius:10px;
            }
            QLabel#ResearchCardTitle{color:#8e9bb0;font-size:11px;}
            QLabel#ResearchCardValue{font-size:18px;font-weight:800;color:#f4f7fb;}
            QLabel#MostCommonBoard{
                padding:8px 12px;background:#202a3b;border:1px solid #3b4b64;
                border-radius:7px;color:#dce52f;font-weight:800;
            }
            QLabel#ResearchSummary{
                padding:11px;background:#192131;border:1px solid #303d52;
                border-radius:8px;font-weight:650;
            }
            QPushButton#PrimaryButton{
                background:#dce52f;color:#11151c;font-weight:800;
                border-radius:6px;padding:8px 15px;
            }
            QScrollArea#BoardCardScroll{background:transparent;border:none;}
            QFrame#BoardResearchCard{
                background:#111925;border:1px solid #2b3547;border-radius:11px;
            }
            QFrame#BoardResearchCard:hover{
                background:#172236;border:1px solid #3b82f6;
            }
            QLabel#BoardFamily{font-size:16px;font-weight:850;color:#f3f6fb;}
            QLabel#BoardMeta{font-size:12px;color:#91a0b6;}
            QLabel#BoardHands{font-size:14px;font-weight:750;color:#dce52f;}
            QLabel#BoardCaption{font-size:11px;color:#91a0b6;}
            QFrame#MetricBox{
                background:#0e1520;border:1px solid #273247;border-radius:8px;
            }
            QLabel#MetricTitle{font-size:10px;color:#8e9bb0;}
            QLabel#MetricValue{font-size:17px;font-weight:850;color:#f4f7fb;}
            QLabel#MetricSub{font-size:10px;color:#69d58c;}
            QPushButton#CardDetailButton{
                background:#26344d;border:1px solid #405271;border-radius:6px;
                padding:7px;color:#f3f6fb;font-weight:700;
            }
            QPushButton#CardDetailButton:hover{background:#315086;}
            QLabel#DetailTitle{font-size:17px;font-weight:850;color:#f4f7fb;}
            QLabel#DetailText{
                padding:10px;background:#0f1621;border:1px solid #273247;
                border-radius:8px;color:#cbd5e1;
            }
            """
        )
        self._street_changed()

    def _summary_card(self, title: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ResearchCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(13, 9, 13, 9)
        title_label = QLabel(title)
        title_label.setObjectName("ResearchCardTitle")
        value_label = QLabel(value)
        value_label.setObjectName("ResearchCardValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame.value_label = value_label
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return frame

    def _street_changed(self) -> None:
        self.turn_combo.setEnabled(self.street_combo.currentData() == "TURN")
        self.refresh_filters()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(100, self.refresh_filters)

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
                boards = con.execute(
                    "SELECT flop, turn FROM hands "
                    "WHERE flop IS NOT NULL AND TRIM(flop)<>'' LIMIT 50000"
                ).fetchall()

            self.site_combo.clear()
            self.site_combo.addItem("Tüm Siteler", "")
            for row in sites:
                if row[0]:
                    self.site_combo.addItem(str(row[0]), str(row[0]))

            self.stakes_combo.clear()
            self.stakes_combo.addItem("Tüm Limitler", "")
            for row in stakes:
                if row[0]:
                    self.stakes_combo.addItem(str(row[0]), str(row[0]))

            detail = self.view_combo.currentData() == "DETAIL"
            turn_mode = self.street_combo.currentData() == "TURN"
            values: set[str] = set()
            for flop, turn_card in boards:
                base = (
                    self.service._texture_family(str(flop or ""))
                    if detail
                    else self.service._simple_flop_family(str(flop or ""))
                )
                value = (
                    f"{base} › {self.service._turn_transition(str(flop or ''), str(turn_card or ''))}"
                    if turn_mode
                    else base
                )
                values.add(value)

            self.texture_combo.clear()
            self.texture_combo.addItem("Tüm Gruplar", "")
            for value in sorted(values):
                if value and "Unknown" not in value:
                    self.texture_combo.addItem(value, value)
        except Exception as exc:
            QMessageBox.critical(
                self, "Filtre Hatası", f"{type(exc).__name__}: {exc}"
            )

    def load_entities(self) -> None:
        try:
            rows = self.service.available_entities(
                str(self.mode_combo.currentData()),
                str(self.site_combo.currentData() or ""),
                str(self.stakes_combo.currentData() or ""),
                100,
            )
            self.entity_combo.clear()
            for key, label, hands in rows:
                self.entity_combo.addItem(f"{label} ({hands:,} hands)", key)
            self.status_label.setText(f"{len(rows)} research kaynağı yüklendi.")
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
                self, "Research Lab", "Önce profil yükleyip seç."
            )
            return

        args = dict(
            mode=str(self.mode_combo.currentData()),
            entity_name=entity,
            site=str(self.site_combo.currentData() or ""),
            stakes=str(self.stakes_combo.currentData() or ""),
            position=str(self.position_combo.currentData() or ""),
            texture_filter=str(self.texture_combo.currentData() or ""),
            minimum_sample=self.minimum_sample.value(),
            view_mode=str(self.view_combo.currentData()),
            street_mode=str(self.street_combo.currentData()),
            turn_filter=(
                str(self.turn_combo.currentData() or "")
                if self.street_combo.currentData() == "TURN"
                else ""
            ),
        )
        self.load_button.setEnabled(False)
        self.analyze_button.setEnabled(False)
        self.status_label.setText("Araştırma kartları hesaplanıyor…")
        self.worker_thread = QThread(self)
        self.worker = SizeBoardWorker(self.database_path, args)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._analysis_finished)
        self.worker.failed.connect(self._analysis_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    @Slot(dict)
    def _analysis_finished(self, report: dict[str, Any]) -> None:
        rows = report.get("rows", [])
        strongest = report.get("strongest_difference", {})
        self._all_rows = list(rows)
        self._refresh_result_texture_filter()
        self._apply_result_filters()
        self.groups_card.value_label.setText(str(len(rows)))
        self.actionable_card.value_label.setText(
            str(report.get("actionable_groups", 0))
        )
        if strongest:
            self.strongest_card.value_label.setText(
                f"{strongest['position']} {strongest['size_bucket']}"
            )
            self.score_card.value_label.setText(
                f"{float(strongest['difference_score']):.0f}"
            )
            self.confidence_card.value_label.setText(
                str(strongest["confidence"])
            )
        else:
            self.strongest_card.value_label.setText("—")
            self.score_card.value_label.setText("0")
            self.confidence_card.value_label.setText("—")
        self.summary_label.setText(str(report.get("summary") or ""))
        self.evidence_label.setText(str(report.get("evidence") or ""))
        if rows:
            self._show_detail(rows[0])

    def _refresh_result_texture_filter(self) -> None:
        current = str(self.result_texture_combo.currentData() or "")
        totals: dict[str, int] = {}
        for row in self._all_rows:
            texture = str(row.get("texture") or "Unknown")
            totals[texture] = totals.get(texture, 0) + int(row.get("hands") or 0)

        self.result_texture_combo.blockSignals(True)
        self.result_texture_combo.clear()
        self.result_texture_combo.addItem("Tüm Board Tipleri", "")
        for texture, hands in sorted(totals.items(), key=lambda item: (-item[1], item[0])):
            self.result_texture_combo.addItem(f"{texture} ({hands:,} el)", texture)
        index = self.result_texture_combo.findData(current)
        self.result_texture_combo.setCurrentIndex(index if index >= 0 else 0)
        self.result_texture_combo.blockSignals(False)

        if totals:
            texture, hands = max(totals.items(), key=lambda item: item[1])
            grand_total = sum(totals.values())
            share = (hands / grand_total * 100.0) if grand_total else 0.0
            self.most_common_label.setText(
                f"En çok board tipi: {texture} — {hands:,} el (%{share:.1f})"
            )
        else:
            self.most_common_label.setText("En çok board tipi: —")

    @Slot()
    def _apply_result_filters(self) -> None:
        rows = list(self._all_rows)
        texture = str(self.result_texture_combo.currentData() or "")
        if texture:
            rows = [row for row in rows if str(row.get("texture") or "") == texture]

        sort_key = str(self.result_sort_combo.currentData() or "HANDS")
        key_map = {
            "HANDS": "hands",
            "EXPLOIT": "difference_score",
            "FLOP": "flop_cbet",
            "TURN": "turn_barrel",
            "RIVER": "river_barrel",
            "WWSF": "wwsf",
            "WSD": "wsd",
        }
        field = key_map.get(sort_key, "hands")
        rows.sort(key=lambda row: float(row.get(field) or 0), reverse=True)

        limit = int(self.result_limit_combo.currentData() or 0)
        shown = rows[:limit] if limit > 0 else rows
        self._fill_cards(shown)
        self.status_label.setText(
            f"{len(shown)} / {len(rows)} araştırma kartı gösteriliyor."
        )
        if shown:
            self._show_detail(shown[0])

    def _clear_layout(self, layout: QVBoxLayout | QHBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _fill_cards(self, rows: list[dict[str, Any]]) -> None:
        self._clear_layout(self.card_layout)
        if not rows:
            empty = QLabel("Filtrelere uygun araştırma grubu bulunamadı.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setObjectName("PageSubtitle")
            self.card_layout.addWidget(empty)
            self.card_layout.addStretch()
            return
        for row in rows:
            card = BoardResearchCard(row)
            card.selected.connect(self._show_detail)
            self.card_layout.addWidget(card)
        self.card_layout.addStretch()

    @Slot(dict)
    def _show_detail(self, row: dict[str, Any]) -> None:
        self._clear_layout(self.detail_board_layout)
        board = str(row.get("representative_board") or "")
        for card in board.split():
            self.detail_board_layout.addWidget(PokerCard(card))
        self.detail_board_layout.addStretch()

        self.detail_family.setText(
            f"{row.get('texture', '—')}\n"
            f"{row.get('position', '—')} • {row.get('size_bucket', '—')}\n"
            f"{int(row.get('hands') or 0):,} el"
        )
        self.detail_metrics.setText(
            f"Flop: {float(row.get('flop_cbet') or 0):.1f}%  |  "
            f"Avg {float(row.get('flop_avg_bet_pct') or 0):.1f}% pot\n"
            f"Turn: {float(row.get('turn_barrel') or 0):.1f}%  |  "
            f"Avg {float(row.get('turn_avg_bet_pct') or 0):.1f}% pot\n"
            f"River: {float(row.get('river_barrel') or 0):.1f}%  |  "
            f"Avg {float(row.get('river_avg_bet_pct') or 0):.1f}% pot\n\n"
            f"WWSF: {float(row.get('wwsf') or 0):.1f}%\n"
            f"W$SD: {float(row.get('wsd') or 0):.1f}%\n"
            f"Exploit Score: {float(row.get('difference_score') or 0):.0f}\n"
            f"Güven: {row.get('confidence', '—')}\n\n"
            f"Size DNA: {row.get('size_dna', '—')}\n"
            f"Öneri: {row.get('interpretation', '—')}"
        )

        representatives = row.get("representative_boards") or []
        lines = ["Aynı gruptaki en sık gerçek boardlar:"]
        for item in representatives:
            lines.append(
                f"• {item.get('board', '—')} — {int(item.get('hands') or 0):,} el"
            )
        self.detail_representatives.setText("\n".join(lines))

    @Slot(str)
    def _analysis_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Analiz Hatası", message)
        self.status_label.setText("Analiz başarısız.")

    def _cleanup_worker(self) -> None:
        self.load_button.setEnabled(True)
        self.analyze_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
