from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (
    QApplication,
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
    QDoubleSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from services.size_board_strategy_service import SizeBoardStrategyService
from services.gto_reference_service import GTOReferenceService


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
            primary_args = dict(self.args)
            baseline_mode = str(primary_args.pop("_baseline_mode", "POOL"))
            report = self.service.analyze(**primary_args)
            if str(primary_args.get("mode") or "").upper() == baseline_mode:
                pool_report = report
            else:
                pool_args = dict(primary_args)
                pool_args["mode"] = baseline_mode
                pool_args["entity_name"] = "__POOL__"
                pool_report = self.service.analyze(**pool_args)
            report["pool_rows"] = pool_report.get("rows", [])
            report["baseline_mode"] = baseline_mode
            self.finished.emit(report)
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


class DistributionRow(QWidget):
    def __init__(self, label: str, pct: float, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        name = QLabel(label)
        name.setObjectName("DistributionLabel")
        name.setFixedWidth(58)

        bar = QProgressBar()
        bar.setObjectName("DistributionBar")
        bar.setRange(0, 1000)
        bar.setValue(max(0, min(1000, round(float(pct) * 10))))
        bar.setTextVisible(False)
        bar.setFixedHeight(9)

        value = QLabel(f"{float(pct):.1f}%  ({int(count):,})")
        value.setObjectName("DistributionValue")
        value.setMinimumWidth(82)
        value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(name)
        layout.addWidget(bar, 1)
        layout.addWidget(value)


class DistributionHistogram(QFrame):
    """Compact, dependency-free histogram for the selected street."""

    COLORS = (
        "#38bdf8", "#22d3ee", "#34d399", "#a3e635",
        "#facc15", "#fb923c", "#f87171",
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DistributionHistogram")
        self.setMinimumHeight(190)
        self.root = QHBoxLayout(self)
        self.root.setContentsMargins(10, 12, 10, 8)
        self.root.setSpacing(7)

    def set_distribution(self, distribution: list[dict[str, Any]]) -> None:
        while self.root.count():
            item = self.root.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

        maximum = max((float(item.get("pct") or 0) for item in distribution), default=0.0)
        for index, item in enumerate(distribution):
            label = str(item.get("bucket") or "—")
            pct = float(item.get("pct") or 0.0)
            count = int(item.get("count") or 0)
            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(4)
            column_layout.addStretch()

            pct_label = QLabel(f"{pct:.1f}%")
            pct_label.setObjectName("HistogramValue")
            pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column_layout.addWidget(pct_label)

            bar = QFrame()
            bar.setObjectName("HistogramBar")
            bar_height = 8 if maximum <= 0 else max(8, round(105 * pct / maximum))
            bar.setFixedHeight(bar_height)
            color = self.COLORS[min(index, len(self.COLORS) - 1)]
            bar.setStyleSheet(
                f"background:{color};border:1px solid {color};border-radius:5px;"
            )
            tooltip = f"{label}\nPay: %{pct:.1f}\nSample: {count:,}"
            bar.setToolTip(tooltip)
            pct_label.setToolTip(tooltip)
            column_layout.addWidget(bar)

            bucket_label = QLabel(label)
            bucket_label.setObjectName("HistogramBucket")
            bucket_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bucket_label.setToolTip(tooltip)
            column_layout.addWidget(bucket_label)
            self.root.addWidget(column, 1)


class SizeDNAWidget(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SizeDNAPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel("SIZE DNA 2.0")
        title.setObjectName("DNATitle")
        self.open_label = QLabel("Open —")
        self.open_label.setObjectName("DNAOpen")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.open_label)
        root.addLayout(head)

        self.street_labels: dict[str, dict[str, QLabel]] = {}
        for street in ("Flop", "Turn", "River"):
            card = QFrame()
            card.setObjectName("DNAStreetCard")
            grid = QGridLayout(card)
            grid.setContentsMargins(9, 7, 9, 7)
            grid.setHorizontalSpacing(9)
            name = QLabel(street.upper())
            name.setObjectName("DNAStreetName")
            frequency = QLabel("Freq —")
            average = QLabel("Avg —")
            sample = QLabel("n=0")
            tendency = QLabel("NO DATA")
            tendency.setObjectName("DNATendency")
            profile = QLabel("Street profile —")
            profile.setObjectName("DNAProfile")
            grid.addWidget(name, 0, 0)
            grid.addWidget(frequency, 0, 1)
            grid.addWidget(average, 0, 2)
            grid.addWidget(sample, 0, 3)
            grid.addWidget(tendency, 0, 4)
            grid.addWidget(profile, 1, 0, 1, 5)
            self.street_labels[street.lower()] = {
                "frequency": frequency, "average": average,
                "sample": sample, "tendency": tendency, "profile": profile,
            }
            root.addWidget(card)

        self.showdown_label = QLabel("WWSF —   WTSD —   W$SD —")
        self.showdown_label.setObjectName("DNAShowdown")
        root.addWidget(self.showdown_label)

    def set_row(self, row: dict[str, Any]) -> None:
        dna = row.get("size_dna_data") or {}
        avg_open = float(dna.get("open_avg_bb") or row.get("avg_size_bb") or 0.0)
        min_open = float(dna.get("open_min_bb") or 0.0)
        max_open = float(dna.get("open_max_bb") or 0.0)
        open_text = f"Open {avg_open:.2f}x"
        if min_open > 0 and max_open > 0:
            open_text += f"  [{min_open:.2f}–{max_open:.2f}x]"
        self.open_label.setText(open_text)

        specs = (
            ("flop", "flop_frequency", "flop_avg_bet_pct", "flop_size_sample"),
            ("turn", "turn_frequency", "turn_avg_bet_pct", "turn_size_sample"),
            ("river", "river_frequency", "river_avg_bet_pct", "river_size_sample"),
        )
        for street, freq_key, size_key, sample_key in specs:
            freq = float(dna.get(freq_key) or row.get({"flop":"flop_cbet","turn":"turn_barrel","river":"river_barrel"}[street]) or 0.0)
            size = float(dna.get(size_key) or row.get(f"{street}_avg_bet_pct") or 0.0)
            sample = int(dna.get(sample_key) or row.get(f"{street}_bet_size_sample") or 0)
            tag = "OVERBET" if size > 100 else "LARGE" if size >= 75 else "SMALL" if 0 < size <= 40 else "MID" if size else "NO DATA"
            pressure = "High pressure" if freq >= 65 else "Selective pressure" if freq >= 40 else "Low pressure"
            profile = f"{pressure} • {tag.lower()} sizing"
            labels = self.street_labels[street]
            labels["frequency"].setText(f"Freq {freq:.1f}%")
            labels["average"].setText(f"Avg {size:.1f}% pot" if sample else "Avg —")
            labels["sample"].setText(f"n={sample:,}")
            labels["tendency"].setText(tag)
            labels["tendency"].setProperty("overbet", tag == "OVERBET")
            labels["tendency"].style().unpolish(labels["tendency"])
            labels["tendency"].style().polish(labels["tendency"])
            labels["profile"].setText(profile if sample else "Street profile —")

        self.showdown_label.setText(
            f"WWSF {float(dna.get('wwsf') or row.get('wwsf') or 0):.1f}%   "
            f"WTSD {float(dna.get('wtsd') or row.get('wtsd') or 0):.1f}%   "
            f"W$SD {float(dna.get('wsd') or row.get('wsd') or 0):.1f}%"
        )


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
        pool_delta = float(row.get("pool_max_delta") or 0.0)
        pool_metric = str(row.get("pool_delta_metric") or "—")
        comparison = QLabel(
            f"Pool Δ {pool_metric} {pool_delta:+.1f} pp • "
            f"Score {float(row.get('pool_exploit_score') or 0):.0f}"
            if row.get("pool_match_found") else "Pool eşleşmesi yok"
        )
        comparison.setObjectName("BoardDelta")
        identity.addWidget(family)
        identity.addWidget(meta)
        identity.addWidget(hands)
        identity.addWidget(comparison)
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
        root.addWidget(MetricBox("WTSD", f"{float(row.get('wtsd') or 0):.1f}%"))
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
            f"Pool güven: {row.get('pool_delta_confidence', '—')} "
            f"(n={int(row.get('pool_delta_sample') or 0):,})\n"
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
        self.gto_service = GTOReferenceService()
        self.worker_thread: QThread | None = None
        self.worker: SizeBoardWorker | None = None
        self._all_rows: list[dict[str, Any]] = []
        self._pool_rows: list[dict[str, Any]] = []
        self._baseline_mode = "POOL"
        self._selected_row: dict[str, Any] | None = None
        self._current_exploit_plan_text = ""
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
        self.baseline_combo = QComboBox()
        self.baseline_combo.addItem("Human Pool", "POOL")
        self.baseline_combo.addItem("All Pool", "ALL_POOL")
        self.load_button.clicked.connect(self.load_entities)
        self.analyze_button.clicked.connect(self.run_analysis)
        self.view_combo.currentIndexChanged.connect(self.refresh_filters)
        self.street_combo.currentIndexChanged.connect(self._street_changed)
        self.mode_combo.currentIndexChanged.connect(self.load_entities)

        buttons = QHBoxLayout()
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.analyze_button)
        buttons.addSpacing(12)
        buttons.addWidget(QLabel("Karşılaştırma:"))
        buttons.addWidget(self.baseline_combo)
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
            ("En Yüksek Gerçek Pool Exploit", "POOL_SCORE"),
            ("En Büyük Pool Sapması", "POOL_DELTA"),
            ("En Büyük GTO Sapması", "GTO_DELTA"),
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
        self.result_delta_combo = QComboBox()
        for label, value in [
            ("Tüm Sapmalar", 0.0), ("≥ 3 pp", 3.0),
            ("≥ 7 pp", 7.0), ("≥ 12 pp", 12.0),
        ]:
            self.result_delta_combo.addItem(label, value)

        self.most_common_label = QLabel("En çok board tipi: —")
        self.most_common_label.setObjectName("MostCommonBoard")

        result_grid.addWidget(QLabel("Board Tipi"), 0, 0)
        result_grid.addWidget(QLabel("Sırala"), 0, 1)
        result_grid.addWidget(QLabel("Göster"), 0, 2)
        result_grid.addWidget(QLabel("Min Sapma"), 0, 3)
        result_grid.addWidget(self.result_texture_combo, 1, 0)
        result_grid.addWidget(self.result_sort_combo, 1, 1)
        result_grid.addWidget(self.result_limit_combo, 1, 2)
        result_grid.addWidget(self.result_delta_combo, 1, 3)
        result_grid.addWidget(self.most_common_label, 1, 4)
        result_grid.setColumnStretch(4, 1)

        self.result_texture_combo.currentIndexChanged.connect(self._apply_result_filters)
        self.result_sort_combo.currentIndexChanged.connect(self._apply_result_filters)
        self.result_limit_combo.currentIndexChanged.connect(self._apply_result_filters)
        self.result_delta_combo.currentIndexChanged.connect(self._apply_result_filters)
        root.addWidget(result_filters)

        # Size-independent total board + GTO comparison panel
        self.total_panel = QFrame()
        self.total_panel.setObjectName("ResultFilters")
        total_layout = QVBoxLayout(self.total_panel)
        total_layout.setContentsMargins(12, 10, 12, 10)
        total_head = QHBoxLayout()
        total_title = QLabel("Board Total + GTO Sapma")
        total_title.setObjectName("DetailTitle")
        self.total_board_combo = QComboBox()
        self.total_board_combo.addItem("Tüm Board Tipleri", "")
        self.save_gto_button = QPushButton("GTO Değerlerini Kaydet")
        self.save_gto_button.setObjectName("CardDetailButton")
        total_head.addWidget(total_title)
        total_head.addStretch()
        total_head.addWidget(QLabel("Board:"))
        total_head.addWidget(self.total_board_combo)
        total_head.addWidget(self.save_gto_button)
        total_layout.addLayout(total_head)

        self.total_table = QTableWidget(3, 8)
        self.total_table.setHorizontalHeaderLabels([
            "Street", "Opportunity", "Bet", "Check", "Gerçek %",
            "Avg Size", "GTO %", "Sapma"
        ])
        self.total_table.verticalHeader().setVisible(False)
        self.total_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.total_table.setMaximumHeight(150)
        total_layout.addWidget(self.total_table)
        self.total_note = QLabel(
            "Toplamlar open size ve kart görünüm limitinden bağımsızdır. "
            "GTO hücresine çift tıklayıp değeri yazabilirsin."
        )
        self.total_note.setObjectName("PageSubtitle")
        total_layout.addWidget(self.total_note)
        root.addWidget(self.total_panel)
        self.total_board_combo.currentIndexChanged.connect(self._refresh_total_panel)
        self.save_gto_button.clicked.connect(self._save_gto_values)

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
        self.detail_panel.setMinimumWidth(500)
        self.detail_panel.setMaximumWidth(650)
        panel_layout = QVBoxLayout(self.detail_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setObjectName("DetailScroll")
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.detail_content = QWidget()
        detail_layout = QVBoxLayout(self.detail_content)
        detail_layout.setContentsMargins(17, 17, 17, 17)
        detail_layout.setSpacing(11)
        self.detail_scroll.setWidget(self.detail_content)
        panel_layout.addWidget(self.detail_scroll)
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

        self.detail_stats = QFrame()
        self.detail_stats.setObjectName("DetailStats")
        stats_grid = QGridLayout(self.detail_stats)
        stats_grid.setContentsMargins(8, 8, 8, 8)
        stats_grid.setSpacing(7)
        self.detail_stat_labels: dict[str, QLabel] = {}
        for index, (key, title) in enumerate((
            ("group", "GROUP SAMPLE"), ("board", "BOARD SAMPLE"),
            ("frequency", "BOARD FREQUENCY"), ("confidence", "CONFIDENCE"),
        )):
            box = QFrame()
            box.setObjectName("DetailStatBox")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(8, 7, 8, 7)
            caption = QLabel(title)
            caption.setObjectName("DetailStatTitle")
            value = QLabel("—")
            value.setObjectName("DetailStatValue")
            value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box_layout.addWidget(caption)
            box_layout.addWidget(value)
            stats_grid.addWidget(box, index // 2, index % 2)
            self.detail_stat_labels[key] = value

        self.exploit_summary = QLabel("Exploit özeti —")
        self.exploit_summary.setObjectName("ExploitSummary")
        self.exploit_summary.setWordWrap(True)

        self.comparison_panel = QFrame()
        self.comparison_panel.setObjectName("ComparisonPanel")
        comparison_layout = QVBoxLayout(self.comparison_panel)
        comparison_layout.setContentsMargins(10, 10, 10, 10)
        comparison_layout.setSpacing(7)
        comparison_head = QHBoxLayout()
        comparison_title = QLabel("BOARD vs POOL / GTO 2.0")
        comparison_title.setObjectName("DNATitle")
        self.comparison_baseline_label = QLabel("Human Pool")
        self.comparison_baseline_label.setObjectName("ComparisonBaseline")
        comparison_head.addWidget(comparison_title)
        comparison_head.addStretch()
        comparison_head.addWidget(self.comparison_baseline_label)
        comparison_layout.addLayout(comparison_head)

        self.comparison_table = QTableWidget(5, 7)
        self.comparison_table.setHorizontalHeaderLabels([
            "Metric", "Selected", "Pool", "Δ Pool", "GTO", "Δ GTO", "Signal"
        ])
        self.comparison_table.verticalHeader().setVisible(False)
        self.comparison_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.comparison_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.comparison_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.comparison_table.setMinimumHeight(205)
        comparison_layout.addWidget(self.comparison_table)
        self.comparison_summary = QLabel("Karşılaştırma için bir board grubu seç.")
        self.comparison_summary.setObjectName("ComparisonSummary")
        self.comparison_summary.setWordWrap(True)
        comparison_layout.addWidget(self.comparison_summary)

        self.leak_panel = QFrame()
        self.leak_panel.setObjectName("LeakPanel")
        leak_root = QVBoxLayout(self.leak_panel)
        leak_root.setContentsMargins(10, 10, 10, 10)
        leak_root.setSpacing(7)
        leak_head = QHBoxLayout()
        leak_title = QLabel("TOP ACTIONABLE POOL LEAKS")
        leak_title.setObjectName("DNATitle")
        self.pool_score_label = QLabel("SCORE —")
        self.pool_score_label.setObjectName("PoolScore")
        leak_head.addWidget(leak_title)
        leak_head.addStretch()
        leak_head.addWidget(self.pool_score_label)
        leak_root.addLayout(leak_head)
        self.leak_container = QWidget()
        self.leak_layout = QVBoxLayout(self.leak_container)
        self.leak_layout.setContentsMargins(0, 0, 0, 0)
        self.leak_layout.setSpacing(6)
        leak_root.addWidget(self.leak_container)

        self.coach_panel = QFrame()
        self.coach_panel.setObjectName("CoachPanel")
        coach_root = QVBoxLayout(self.coach_panel)
        coach_root.setContentsMargins(10, 10, 10, 10)
        coach_root.setSpacing(7)
        coach_head = QHBoxLayout()
        coach_title = QLabel("BOARD EXPLOIT COACH 2.0")
        coach_title.setObjectName("DNATitle")
        self.copy_plan_button = QPushButton("Planı Kopyala")
        self.copy_plan_button.setObjectName("CardDetailButton")
        self.copy_plan_button.clicked.connect(self._copy_exploit_plan)
        coach_head.addWidget(coach_title)
        coach_head.addStretch()
        coach_head.addWidget(self.copy_plan_button)
        coach_root.addLayout(coach_head)
        self.coach_context = QLabel("Board seçildiğinde exploit planı hazırlanır.")
        self.coach_context.setObjectName("CoachContext")
        self.coach_context.setWordWrap(True)
        coach_root.addWidget(self.coach_context)
        self.coach_container = QWidget()
        self.coach_layout = QVBoxLayout(self.coach_container)
        self.coach_layout.setContentsMargins(0, 0, 0, 0)
        self.coach_layout.setSpacing(6)
        coach_root.addWidget(self.coach_container)

        self.size_dna_widget = SizeDNAWidget()

        self.distribution_title = QLabel("BET SIZE DISTRIBUTION")
        self.distribution_title.setObjectName("DNATitle")
        self.distribution_street_combo = QComboBox()
        self.distribution_street_combo.addItem("Flop", "flop")
        self.distribution_street_combo.addItem("Turn", "turn")
        self.distribution_street_combo.addItem("River", "river")
        self.distribution_street_combo.currentIndexChanged.connect(self._refresh_distribution)
        distribution_head = QHBoxLayout()
        distribution_head.addWidget(self.distribution_title)
        distribution_head.addStretch()
        distribution_head.addWidget(self.distribution_street_combo)

        self.distribution_container = QWidget()
        self.distribution_layout = QVBoxLayout(self.distribution_container)
        self.distribution_layout.setContentsMargins(0, 0, 0, 0)
        self.distribution_layout.setSpacing(5)
        self.distribution_summary = QLabel("Distribution summary —")
        self.distribution_summary.setObjectName("DistributionSummary")
        self.distribution_summary.setWordWrap(True)
        self.distribution_histogram = DistributionHistogram()

        self.detail_representatives = QLabel("")
        self.detail_representatives.setObjectName("DetailText")
        self.detail_representatives.setWordWrap(True)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_board)
        detail_layout.addWidget(self.detail_family)
        detail_layout.addWidget(self.detail_stats)
        detail_layout.addWidget(self.detail_metrics)
        detail_layout.addWidget(self.exploit_summary)
        detail_layout.addWidget(self.comparison_panel)
        detail_layout.addWidget(self.leak_panel)
        detail_layout.addWidget(self.coach_panel)
        detail_layout.addWidget(self.size_dna_widget)
        detail_layout.addLayout(distribution_head)
        detail_layout.addWidget(self.distribution_summary)
        detail_layout.addWidget(self.distribution_histogram)
        detail_layout.addWidget(self.distribution_container)
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
            QLabel#BoardDelta{
                padding:3px 6px;background:#172840;border-radius:5px;
                color:#7dd3fc;font-size:10px;font-weight:800;
            }
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
            QScrollArea#DetailScroll{background:transparent;border:none;}
            QScrollArea#DetailScroll > QWidget > QWidget{background:transparent;}
            QFrame#DetailStats{background:transparent;border:none;}
            QFrame#DetailStatBox{
                background:#0e1520;border:1px solid #273247;border-radius:8px;
            }
            QLabel#DetailStatTitle{font-size:9px;color:#7f8da3;font-weight:800;}
            QLabel#DetailStatValue{font-size:16px;color:#f4f7fb;font-weight:900;}
            QLabel#ExploitSummary{
                padding:12px;background:#18243a;border:1px solid #3b82f6;
                border-radius:8px;color:#dbeafe;font-weight:750;
            }
            QFrame#ComparisonPanel{
                background:#0f1725;border:1px solid #33445f;border-radius:9px;
            }
            QLabel#ComparisonBaseline{
                padding:4px 8px;background:#1e3a5f;border-radius:5px;
                color:#93c5fd;font-size:10px;font-weight:850;
            }
            QLabel#ComparisonSummary{
                padding:8px;background:#111e30;border-radius:7px;
                color:#cbd5e1;font-size:11px;font-weight:650;
            }
            QFrame#LeakPanel{
                background:#121a26;border:1px solid #3b4658;border-radius:9px;
            }
            QLabel#PoolScore{
                padding:4px 9px;background:#3b2030;border:1px solid #7f3652;
                border-radius:5px;color:#fda4af;font-size:11px;font-weight:900;
            }
            QFrame#LeakCard{
                background:#0c1420;border:1px solid #29384d;border-radius:7px;
            }
            QLabel#LeakMetric{color:#f4f7fb;font-size:11px;font-weight:900;}
            QLabel#LeakValues{color:#9fb0c6;font-size:10px;}
            QLabel#LeakSeverity{
                padding:3px 7px;background:#26354b;border-radius:4px;
                color:#facc15;font-size:9px;font-weight:900;
            }
            QLabel#LeakSeverity[severity="critical"]{background:#4c1d2a;color:#fb7185;}
            QLabel#LeakSeverity[severity="strong"]{background:#3b2f16;color:#facc15;}
            QLabel#LeakSeverity[severity="moderate"]{background:#17364a;color:#7dd3fc;}
            QFrame#CoachPanel{
                background:#101a20;border:1px solid #285442;border-radius:9px;
            }
            QLabel#CoachContext{
                padding:8px;background:#11261f;border-radius:6px;
                color:#86efac;font-size:10px;font-weight:700;
            }
            QFrame#CoachCard{
                background:#0b1517;border:1px solid #24483b;border-radius:7px;
            }
            QLabel#CoachIndex{
                min-width:25px;max-width:25px;min-height:25px;max-height:25px;
                background:#166534;border-radius:12px;color:#dcfce7;font-weight:900;
            }
            QLabel#CoachAction{color:#f0fdf4;font-size:11px;font-weight:900;}
            QLabel#CoachEvidence{color:#91a69d;font-size:10px;}
            QTableWidget{
                background:#0b1220;alternate-background-color:#101a2a;
                border:1px solid #26364d;gridline-color:#26364d;color:#dbe5f3;
            }
            QHeaderView::section{
                background:#19263a;color:#93a4ba;border:none;
                border-right:1px solid #2b3b53;padding:5px;font-size:9px;font-weight:800;
            }
            QFrame#SizeDNAPanel{
                background:#101827;border:1px solid #38506e;border-radius:9px;
            }
            QLabel#DNATitle{font-size:11px;font-weight:900;color:#dce52f;}
            QLabel#DNAOpen{font-size:12px;font-weight:850;color:#f4f7fb;}
            QFrame#DNAStreetCard{background:#0b1220;border:1px solid #26344b;border-radius:7px;}
            QLabel#DNAStreetName{color:#93c5fd;font-size:10px;font-weight:900;}
            QLabel#DNATendency{color:#a3e635;font-size:10px;font-weight:900;}
            QLabel#DNATendency[overbet="true"]{color:#fb7185;}
            QLabel#DNAProfile{color:#8796ac;font-size:10px;}
            QLabel#DNAShowdown{
                padding:7px;background:#172236;border-radius:6px;color:#7ee2a8;
                font-weight:800;
            }
            QLabel#DistributionLabel,QLabel#DistributionValue{
                color:#aebbd0;font-size:10px;
            }
            QProgressBar#DistributionBar{
                background:#111925;border:1px solid #2a3950;border-radius:4px;
            }
            QProgressBar#DistributionBar::chunk{
                background:#4d73e6;border-radius:3px;
            }
            QFrame#DistributionHistogram{
                background:#0b1220;border:1px solid #26344b;border-radius:8px;
            }
            QLabel#HistogramValue{color:#dbeafe;font-size:9px;font-weight:800;}
            QLabel#HistogramBucket{color:#8391a6;font-size:8px;}
            QLabel#DistributionSummary{
                padding:8px;background:#111b2b;border:1px solid #293951;
                border-radius:7px;color:#cbd5e1;font-size:11px;
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
            _baseline_mode=str(self.baseline_combo.currentData() or "POOL"),
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
        self._pool_rows = list(report.get("pool_rows") or [])
        self._baseline_mode = str(report.get("baseline_mode") or "POOL")
        self._attach_comparison_deltas()
        self._refresh_total_board_filter()
        self._refresh_total_panel()
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

    def _refresh_total_board_filter(self) -> None:
        current = str(self.total_board_combo.currentData() or "")
        totals: dict[str, int] = {}
        for row in self._all_rows:
            texture = str(row.get("texture") or "Unknown")
            totals[texture] = totals.get(texture, 0) + int(row.get("hands") or 0)
        self.total_board_combo.blockSignals(True)
        self.total_board_combo.clear()
        self.total_board_combo.addItem("Tüm Board Tipleri", "")
        for texture, hands in sorted(totals.items(), key=lambda x: (-x[1], x[0])):
            self.total_board_combo.addItem(f"{texture} ({hands:,} el)", texture)
        idx = self.total_board_combo.findData(current)
        self.total_board_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.total_board_combo.blockSignals(False)

    @Slot()
    def _refresh_total_panel(self) -> None:
        texture = str(self.total_board_combo.currentData() or "")
        rows = [r for r in self._all_rows if not texture or str(r.get("texture") or "") == texture]
        site = str(self.site_combo.currentData() or "")
        stakes = str(self.stakes_combo.currentData() or "")
        family_key = texture or "ALL"
        specs = [
            ("Flop", "flop_sample", "flop_cbet", "flop_avg_bet_pct", "BET"),
            ("Turn", "turn_sample", "turn_barrel", "turn_avg_bet_pct", "BET"),
            ("River", "river_sample", "river_barrel", "river_avg_bet_pct", "BET"),
        ]
        for i, (street, sample_key, freq_key, size_key, metric) in enumerate(specs):
            opp = sum(int(r.get(sample_key) or 0) for r in rows)
            made = sum(float(r.get(freq_key) or 0) * int(r.get(sample_key) or 0) / 100.0 for r in rows)
            freq = (100.0 * made / opp) if opp else 0.0
            size_weight = sum(int(r.get(sample_key) or 0) * float(r.get(freq_key) or 0) / 100.0 for r in rows)
            size_sum = sum(float(r.get(size_key) or 0) * int(r.get(sample_key) or 0) * float(r.get(freq_key) or 0) / 100.0 for r in rows)
            avg_size = size_sum / size_weight if size_weight else 0.0
            gto = self.gto_service.get(site, stakes, family_key, street, metric)
            values = [street, f"{opp:,}", f"{round(made):,}", f"{max(0, opp-round(made)):,}", f"{freq:.1f}%", f"{avg_size:.1f}%", "" if gto is None else f"{gto:.1f}", "—" if gto is None else f"{freq-gto:+.1f} pp"]
            for j, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if j != 6:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.total_table.setItem(i, j, item)
        total_hands = sum(int(r.get("hands") or 0) for r in rows)
        self.total_note.setText(
            f"Seçim: {texture or 'Tüm board tipleri'} • Toplam grup eli: {total_hands:,}. "
            "Frekanslar opportunity ağırlıklıdır; görünümdeki İlk 10/25 sınırından etkilenmez."
        )

    @Slot()
    def _save_gto_values(self) -> None:
        texture = str(self.total_board_combo.currentData() or "") or "ALL"
        site = str(self.site_combo.currentData() or "")
        stakes = str(self.stakes_combo.currentData() or "")
        for row, street in enumerate(("Flop", "Turn", "River")):
            item = self.total_table.item(row, 6)
            text = (item.text().strip().replace("%", "").replace(",", ".") if item else "")
            value = None
            if text:
                try:
                    value = float(text)
                except ValueError:
                    QMessageBox.warning(self, "GTO", f"{street} GTO değeri sayı olmalı.")
                    return
            self.gto_service.set(site, stakes, texture, street, "BET", value)
        self._refresh_total_panel()
        self.status_label.setText("GTO referansları kalıcı olarak kaydedildi.")

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

    def _attach_comparison_deltas(self) -> None:
        """Enrich visible rows without changing the analysis service contract."""
        site = str(self.site_combo.currentData() or "")
        stakes = str(self.stakes_combo.currentData() or "")
        specs = (
            ("Flop", "flop_cbet", "flop_sample", "Flop", "BET", 0.28),
            ("Turn", "turn_barrel", "turn_sample", "Turn", "BET", 0.24),
            ("River", "river_barrel", "river_sample", "River", "BET", 0.20),
            ("WWSF", "wwsf", "wwsf_sample", "ALL", "WWSF", 0.16),
            ("W$SD", "wsd", "wsd_sample", "ALL", "WSD", 0.12),
        )
        for row in self._all_rows:
            pool_row = self._matching_pool_row(row)
            row["pool_match_found"] = pool_row is not None
            pool_deltas: list[tuple[float, str, float, int]] = []
            pool_metrics: list[dict[str, Any]] = []
            gto_deltas: list[tuple[float, str, float]] = []
            texture = str(row.get("texture") or "ALL")

            for label, key, sample_key, street, metric, weight in specs:
                selected_value = float(row.get(key) or 0.0)
                if pool_row is not None:
                    selected_sample = int(row.get(sample_key) or 0)
                    pool_sample = int(pool_row.get(sample_key) or 0)
                    if selected_sample > 0 and pool_sample > 0:
                        pool_value = float(pool_row.get(key) or 0.0)
                        delta = selected_value - pool_value
                        effective_sample = min(selected_sample, pool_sample)
                        pool_deltas.append(
                            (abs(delta), label, delta, effective_sample)
                        )
                        pool_metrics.append({
                            "label": label,
                            "selected": selected_value,
                            "pool": pool_value,
                            "delta": delta,
                            "sample": effective_sample,
                            "weight": weight,
                        })

                gto = self.gto_service.get(site, stakes, texture, street, metric)
                if gto is not None:
                    delta = selected_value - gto
                    gto_deltas.append((abs(delta), label, delta))

            if pool_deltas:
                _, metric, delta, sample = max(pool_deltas, key=lambda item: item[0])
                row["pool_max_delta"] = delta
                row["pool_max_delta_abs"] = abs(delta)
                row["pool_delta_metric"] = metric
                row["pool_delta_sample"] = sample
                row["pool_delta_confidence"] = (
                    "Yüksek" if sample >= 500 else "Orta" if sample >= 200
                    else "Düşük" if sample >= 50 else "Çok Düşük"
                )
            else:
                row["pool_max_delta"] = 0.0
                row["pool_max_delta_abs"] = 0.0
                row["pool_delta_metric"] = "—"
                row["pool_delta_sample"] = 0
                row["pool_delta_confidence"] = "—"

            scored_weight = 0.0
            total_weight = 0.0
            for item in pool_metrics:
                sample = int(item["sample"])
                sample_factor = min(1.0, (sample / 500.0) ** 0.5)
                weight = float(item["weight"])
                scored_weight += abs(float(item["delta"])) * weight * sample_factor
                total_weight += weight
                item["severity"] = (
                    "critical" if abs(float(item["delta"])) >= 12
                    else "strong" if abs(float(item["delta"])) >= 7
                    else "moderate" if abs(float(item["delta"])) >= 3
                    else "aligned"
                )
                item["actionable"] = abs(float(item["delta"])) >= 7 and sample >= 50

            row["pool_comparison_metrics"] = sorted(
                pool_metrics,
                key=lambda item: abs(float(item["delta"])),
                reverse=True,
            )
            row["pool_exploit_score"] = min(
                100.0,
                (scored_weight / total_weight * 4.0) if total_weight else 0.0,
            )
            row["pool_actionable_leaks"] = sum(
                1 for item in pool_metrics if item["actionable"]
            )

            if gto_deltas:
                _, metric, delta = max(gto_deltas, key=lambda item: item[0])
                row["gto_max_delta"] = delta
                row["gto_max_delta_abs"] = abs(delta)
                row["gto_delta_metric"] = metric
            else:
                row["gto_max_delta"] = 0.0
                row["gto_max_delta_abs"] = 0.0
                row["gto_delta_metric"] = "—"

    @Slot()
    def _apply_result_filters(self) -> None:
        rows = list(self._all_rows)
        texture = str(self.result_texture_combo.currentData() or "")
        if texture:
            rows = [row for row in rows if str(row.get("texture") or "") == texture]

        minimum_delta = float(self.result_delta_combo.currentData() or 0.0)
        if minimum_delta > 0:
            rows = [
                row for row in rows
                if max(
                    abs(float(row.get("pool_max_delta") or 0.0)),
                    abs(float(row.get("gto_max_delta") or 0.0)),
                ) >= minimum_delta
            ]

        sort_key = str(self.result_sort_combo.currentData() or "HANDS")
        key_map = {
            "HANDS": "hands",
            "EXPLOIT": "difference_score",
            "POOL_SCORE": "pool_exploit_score",
            "POOL_DELTA": "pool_max_delta_abs",
            "GTO_DELTA": "gto_max_delta_abs",
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
        matched = sum(1 for row in rows if row.get("pool_match_found"))
        self.status_label.setText(
            f"{len(shown)} / {len(rows)} araştırma kartı gösteriliyor • "
            f"Pool eşleşmesi {matched}/{len(rows)}."
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
        self._selected_row = row
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
            f"Exploit Score: {float(row.get('difference_score') or 0):.0f}   •   "
            f"Güven: {row.get('confidence', '—')}\n"
            f"Öneri: {row.get('interpretation', '—')}"
        )
        group_hands = int(row.get("hands") or 0)
        board_hands = int(row.get("representative_board_hands") or 0)
        board_frequency = (100.0 * board_hands / group_hands) if group_hands else 0.0
        self.detail_stat_labels["group"].setText(f"{group_hands:,}")
        self.detail_stat_labels["board"].setText(f"{board_hands:,}")
        self.detail_stat_labels["frequency"].setText(f"{board_frequency:.1f}%")
        self.detail_stat_labels["confidence"].setText(str(row.get("confidence") or "—"))
        self.exploit_summary.setText(
            f"REAL POOL EXPLOIT  {float(row.get('pool_exploit_score') or 0):.0f}/100  •  "
            f"Actionable leak: {int(row.get('pool_actionable_leaks') or 0)}  •  "
            f"{row.get('interpretation') or 'Yeterli ayrışma bulunamadı.'}"
        )
        self._refresh_comparison(row)
        self._refresh_leak_cards(row)
        self._refresh_exploit_coach(row)
        self.size_dna_widget.set_row(row)
        self._refresh_distribution()

        representatives = row.get("representative_boards") or []
        lines = ["Aynı gruptaki en sık gerçek boardlar:"]
        for item in representatives:
            item_hands = int(item.get("hands") or 0)
            item_share = (100.0 * item_hands / group_hands) if group_hands else 0.0
            lines.append(
                f"• {item.get('board', '—')} — {item_hands:,} el (%{item_share:.1f})"
            )
        self.detail_representatives.setText("\n".join(lines))

    def _refresh_leak_cards(self, row: dict[str, Any]) -> None:
        self._clear_layout(self.leak_layout)
        score = float(row.get("pool_exploit_score") or 0.0)
        actionable_count = int(row.get("pool_actionable_leaks") or 0)
        self.pool_score_label.setText(f"SCORE {score:.0f}/100 • {actionable_count} LEAK")
        metrics = [
            item for item in (row.get("pool_comparison_metrics") or [])
            if bool(item.get("actionable"))
        ][:3]
        if not metrics:
            empty = QLabel(
                "Bu grupta ≥7 pp ve en az 50 sample koşulunu geçen güvenilir leak yok."
            )
            empty.setObjectName("PageSubtitle")
            empty.setWordWrap(True)
            self.leak_layout.addWidget(empty)
            return

        for item in metrics:
            card = QFrame()
            card.setObjectName("LeakCard")
            layout = QHBoxLayout(card)
            layout.setContentsMargins(9, 7, 9, 7)
            text_box = QVBoxLayout()
            metric = QLabel(str(item.get("label") or "—"))
            metric.setObjectName("LeakMetric")
            delta = float(item.get("delta") or 0.0)
            direction = "POOL ÜSTÜ" if delta > 0 else "POOL ALTI"
            values = QLabel(
                f"Selected {float(item.get('selected') or 0):.1f}%  •  "
                f"Pool {float(item.get('pool') or 0):.1f}%  •  "
                f"Δ {delta:+.1f} pp  •  n={int(item.get('sample') or 0):,}"
            )
            values.setObjectName("LeakValues")
            text_box.addWidget(metric)
            text_box.addWidget(values)
            severity_key = str(item.get("severity") or "moderate")
            severity = QLabel(
                f"{severity_key.upper()} • {direction}"
            )
            severity.setObjectName("LeakSeverity")
            severity.setProperty("severity", severity_key)
            layout.addLayout(text_box, 1)
            layout.addWidget(severity)
            self.leak_layout.addWidget(card)

    @staticmethod
    def _metric_delta(row: dict[str, Any], label: str) -> float | None:
        for item in row.get("pool_comparison_metrics") or []:
            if str(item.get("label") or "") == label:
                return float(item.get("delta") or 0.0)
        return None

    def _exploit_recommendation(
        self,
        row: dict[str, Any],
        item: dict[str, Any],
    ) -> tuple[str, str]:
        label = str(item.get("label") or "")
        delta = float(item.get("delta") or 0.0)
        high = delta > 0

        if label == "Flop":
            return (
                (
                    "Flop baskısına karşı otomatik fold azalt"
                    if high else "Missed flop cbet sonrası potu daha sık hedefle"
                ),
                (
                    "CBet pool üstü: backdoor ve sağlam bluff-catcher devamlarını koru; "
                    "board avantajın varsa seçici raise kullan."
                    if high else
                    "CBet pool altı: check range daha sık zayıf/capped olabilir; "
                    "gecikmiş stab ve pozisyonel bet fırsatlarını artır."
                ),
            )
        if label == "Turn":
            return (
                (
                    "Turn barrel karşısında flop floatlarını seç"
                    if high else "Flop float + turn stab hattını artır"
                ),
                (
                    "Turn baskısı pool üstü: zayıf flop devamlarını azalt, güçlü draw ve made-hand "
                    "devamlarını koru."
                    if high else
                    "Turn barrel pool altı: flop sonrası vazgeçme sinyali; turn check geldiğinde "
                    "probe/stab frekansını yükselt."
                ),
            )
        if label == "River":
            wsd_delta = self._metric_delta(row, "W$SD")
            if not high:
                return (
                    "Seyrek river betlerine karşı bluff-catch daralt",
                    "River barrel pool altı: bet range daha value yoğun olabilir; marginal "
                    "bluff-catcherlarla gereksiz hero-call azalt.",
                )
            if wsd_delta is not None and wsd_delta <= -3:
                return (
                    "Seçici river bluff-catch genişlet",
                    "River baskısı yüksek ve W$SD pool altında: bluff yoğunluğu sinyali. "
                    "Blocker ve line tutarlılığı uygun bluff-catcherları koru.",
                )
            return (
                "River baskısına karşı value ağırlığını doğrula",
                "River barrel pool üstü fakat düşük W$SD teyidi yok; önce blocker, sizing ve "
                "showdown kalitesini kontrol et, otomatik hero-call yapma.",
            )
        if label == "WWSF":
            return (
                (
                    "Zayıf stabları azalt, güçlü range ile karşı baskı kur"
                    if high else "Delayed stab ve probe frekansını artır"
                ),
                (
                    "WWSF pool üstü: küçük potlar için daha fazla mücadele ediyor."
                    if high else
                    "WWSF pool altı: postflop pot kaybetme oranı yüksek; check ve vazgeçme "
                    "düğümlerine daha sık saldır."
                ),
            )
        if label == "W$SD":
            return (
                (
                    "Showdown karşısında thin bluff-catch azalt"
                    if high else "Value betleri incelt, bluff sinyalini izle"
                ),
                (
                    "W$SD pool üstü: showdown'a ulaşan range güçlü; marginal bluff-catcher ve "
                    "thin value eşiklerini sıkılaştır."
                    if high else
                    "W$SD pool altı: showdown range zayıf; daha ince value al, yüksek river "
                    "barrel eşlik ediyorsa bluff-catch fırsatını değerlendir."
                ),
            )
        return ("Sapmayı incele", "Pool farkını sizing ve board bağlamıyla birlikte doğrula.")

    def _refresh_exploit_coach(self, row: dict[str, Any]) -> None:
        self._clear_layout(self.coach_layout)
        actionable = [
            item for item in (row.get("pool_comparison_metrics") or [])
            if bool(item.get("actionable"))
        ][:3]
        board = str(row.get("representative_board") or "—")
        texture = str(row.get("texture") or "—")
        self.coach_context.setText(
            f"{texture} • {board} • {row.get('position', '—')} • "
            f"{row.get('size_bucket', '—')} • Yalnızca güvenilir Pool sapmaları"
        )
        if not actionable:
            empty = QLabel("Sample ve sapma eşiğini geçen exploit planı yok.")
            empty.setObjectName("PageSubtitle")
            self.coach_layout.addWidget(empty)
            self._current_exploit_plan_text = ""
            self.copy_plan_button.setEnabled(False)
            return

        self.copy_plan_button.setEnabled(True)
        plan_lines = [
            "PokerLab AI • Board Exploit Plan",
            f"Board: {board} | Grup: {texture} | Pozisyon: {row.get('position', '—')}",
        ]
        for index, item in enumerate(actionable, start=1):
            title, explanation = self._exploit_recommendation(row, item)
            card = QFrame()
            card.setObjectName("CoachCard")
            layout = QHBoxLayout(card)
            layout.setContentsMargins(9, 8, 9, 8)
            number = QLabel(str(index))
            number.setObjectName("CoachIndex")
            number.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text_box = QVBoxLayout()
            action = QLabel(title)
            action.setObjectName("CoachAction")
            action.setWordWrap(True)
            evidence = QLabel(
                f"{explanation}\nKanıt: {item.get('label', '—')} "
                f"{float(item.get('selected') or 0):.1f}% vs Pool "
                f"{float(item.get('pool') or 0):.1f}% "
                f"({float(item.get('delta') or 0):+.1f} pp, n={int(item.get('sample') or 0):,})"
            )
            evidence.setObjectName("CoachEvidence")
            evidence.setWordWrap(True)
            text_box.addWidget(action)
            text_box.addWidget(evidence)
            layout.addWidget(number)
            layout.addLayout(text_box, 1)
            self.coach_layout.addWidget(card)
            plan_lines.append(
                f"{index}. {title} — {item.get('label', '—')} "
                f"{float(item.get('delta') or 0):+.1f} pp (n={int(item.get('sample') or 0):,})"
            )
        self._current_exploit_plan_text = "\n".join(plan_lines)

    @Slot()
    def _copy_exploit_plan(self) -> None:
        if not self._current_exploit_plan_text:
            return
        QApplication.clipboard().setText(self._current_exploit_plan_text)
        self.status_label.setText("Board exploit planı panoya kopyalandı.")

    def _matching_pool_row(self, selected: dict[str, Any]) -> dict[str, Any] | None:
        """Return the equivalent position × size × board group in the baseline."""
        keys = ("position", "texture", "size_bucket")
        for candidate in self._pool_rows:
            if all(
                str(candidate.get(key) or "") == str(selected.get(key) or "")
                for key in keys
            ):
                return candidate
        return None

    @staticmethod
    def _comparison_signal(delta: float | None) -> str:
        if delta is None:
            return "No reference"
        absolute = abs(delta)
        if absolute < 3:
            return "Aligned"
        direction = "High" if delta > 0 else "Low"
        if absolute >= 12:
            return f"Very {direction}"
        if absolute >= 7:
            return direction
        return f"Slightly {direction}"

    @staticmethod
    def _delta_text(delta: float | None) -> str:
        return "—" if delta is None else f"{delta:+.1f} pp"

    def _refresh_comparison(self, row: dict[str, Any]) -> None:
        pool_row = self._matching_pool_row(row)
        baseline_name = "Human Pool" if self._baseline_mode == "POOL" else "All Pool"
        self.comparison_baseline_label.setText(baseline_name)
        site = str(self.site_combo.currentData() or "")
        stakes = str(self.stakes_combo.currentData() or "")
        texture = str(row.get("texture") or "ALL")
        specs = (
            ("Flop CBet", "flop_cbet", "Flop", "BET"),
            ("Turn Barrel", "turn_barrel", "Turn", "BET"),
            ("River Barrel", "river_barrel", "River", "BET"),
            ("WWSF", "wwsf", "ALL", "WWSF"),
            ("W$SD", "wsd", "ALL", "WSD"),
        )
        strongest_label = "—"
        strongest_delta = 0.0
        available_pool = 0

        for index, (label, key, street, metric) in enumerate(specs):
            selected_value = float(row.get(key) or 0.0)
            pool_value = (
                float(pool_row.get(key) or 0.0) if pool_row is not None else None
            )
            pool_delta = (
                selected_value - pool_value if pool_value is not None else None
            )
            gto_value = self.gto_service.get(site, stakes, texture, street, metric)
            gto_delta = (
                selected_value - gto_value if gto_value is not None else None
            )
            signal_delta = pool_delta if pool_delta is not None else gto_delta
            signal = self._comparison_signal(signal_delta)
            values = (
                label,
                f"{selected_value:.1f}%",
                "—" if pool_value is None else f"{pool_value:.1f}%",
                self._delta_text(pool_delta),
                "—" if gto_value is None else f"{gto_value:.1f}%",
                self._delta_text(gto_delta),
                signal,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column in {3, 5} and value != "—":
                    delta = pool_delta if column == 3 else gto_delta
                    item.setForeground(
                        QColor("#4ade80") if float(delta or 0) >= 0
                        else QColor("#fb7185")
                    )
                self.comparison_table.setItem(index, column, item)

            if pool_delta is not None:
                available_pool += 1
                if abs(pool_delta) > abs(strongest_delta):
                    strongest_label = label
                    strongest_delta = pool_delta

        if pool_row is None:
            self.comparison_summary.setText(
                f"{baseline_name} içinde aynı pozisyon × size × board grubu bulunamadı. "
                "Min sample değerini düşürerek yeniden çalıştırabilirsin."
            )
        elif available_pool:
            confidence = str(row.get("pool_delta_confidence") or "—")
            sample = int(row.get("pool_delta_sample") or 0)
            self.comparison_summary.setText(
                f"En güçlü pool sapması: {strongest_label} {strongest_delta:+.1f} pp • "
                f"Güven: {confidence} (n={sample:,}) • Referans: {baseline_name} • "
                "Aynı pozisyon, sizing bucket ve board ailesi."
            )

    @Slot()
    def _refresh_distribution(self) -> None:
        self._clear_layout(self.distribution_layout)
        row = self._selected_row or {}
        street = str(self.distribution_street_combo.currentData() or "flop")
        distribution = row.get(f"{street}_size_distribution") or []
        self.distribution_histogram.set_distribution(distribution)
        if not distribution:
            self.distribution_summary.setText("Bu street için sizing örneği yok.")
            empty = QLabel("Bu street için sizing örneği yok.")
            empty.setObjectName("PageSubtitle")
            self.distribution_layout.addWidget(empty)
            return
        total = sum(int(item.get("count") or 0) for item in distribution)
        dominant = max(distribution, key=lambda item: int(item.get("count") or 0))
        avg_size = float(row.get(f"{street}_avg_bet_pct") or 0.0)
        overbet_count = sum(
            int(item.get("count") or 0) for item in distribution
            if str(item.get("bucket") or "") in {"101–125%", ">125%"}
        )
        overbet_share = (100.0 * overbet_count / total) if total else 0.0
        self.distribution_summary.setText(
            f"AVG SIZE  {avg_size:.1f}% pot   •   DOMINANT  {dominant.get('bucket', '—')} "
            f"({float(dominant.get('pct') or 0):.1f}%)   •   SAMPLE  {total:,}   •   "
            f"OVERBET  {overbet_share:.1f}%"
        )
        for item in distribution:
            self.distribution_layout.addWidget(
                DistributionRow(
                    str(item.get("bucket") or "—"),
                    float(item.get("pct") or 0.0),
                    int(item.get("count") or 0),
                )
            )

    @Slot(str)
    def _analysis_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Analiz Hatası", message)
        self.status_label.setText("Analiz başarısız.")

    def _cleanup_worker(self) -> None:
        self.load_button.setEnabled(True)
        self.analyze_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
