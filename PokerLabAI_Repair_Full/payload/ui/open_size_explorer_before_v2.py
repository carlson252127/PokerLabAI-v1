from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from services.open_size_analysis_service import OpenSizeAnalysisService


class OpenSizeWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self, database_path: str, mode: str, entity_name: str,
        site: str, stakes: str, position: str, minimum_sample: int,
    ) -> None:
        super().__init__()
        self.service = OpenSizeAnalysisService(database_path)
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
            self.finished.emit(self.service.analyze(**self.args))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class OpenSizeExplorer(QWidget):
    def __init__(self, database_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database_path = database_path
        self.service = OpenSizeAnalysisService(database_path)
        self.worker_thread: QThread | None = None
        self.worker: OpenSizeWorker | None = None
        self.filters_loaded = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Bot Open Size Explorer")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Open size ile pozisyon, stack, 3-bet maruziyeti, "
            "WWSF ve W$SD ilişkilerini gösterir."
        )
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        frame = QFrame()
        frame.setObjectName("OpenSizeFilters")
        grid = QGridLayout(frame)
        grid.setContentsMargins(16, 16, 16, 16)

        self.mode_combo = QComboBox()
        for label, value in [
            ("Pool", "POOL"), ("Player", "PLAYER"),
            ("Alias Group", "ALIAS"), ("Alias vs Pool", "COMPARE"),
        ]:
            self.mode_combo.addItem(label, value)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)

        self.entity_combo = QComboBox()
        self.entity_combo.setEnabled(False)
        self.entity_combo.setMinimumWidth(220)

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")
        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.position_combo = QComboBox()
        for label, value in [
            ("Tüm Pozisyonlar", ""), ("UTG", "UTG"), ("HJ", "HJ"),
            ("CO", "CO"), ("BTN", "BTN"), ("SB", "SB"), ("BB", "BB"),
        ]:
            self.position_combo.addItem(label, value)

        self.minimum_sample = QSpinBox()
        self.minimum_sample.setRange(1, 10_000_000)
        self.minimum_sample.setValue(50)
        self.minimum_sample.setSingleStep(50)

        labels = ["Mod", "Oyuncu / Alias", "Site", "Stakes", "Pozisyon", "Min Sample"]
        widgets = [
            self.mode_combo, self.entity_combo, self.site_combo,
            self.stakes_combo, self.position_combo, self.minimum_sample,
        ]
        for i, (label, widget) in enumerate(zip(labels, widgets)):
            grid.addWidget(QLabel(label), 0, i)
            grid.addWidget(widget, 1, i)

        self.load_button = QPushButton("Oyuncu/Alias Yükle")
        self.analyze_button = QPushButton("Open Size Analiz Et")
        self.load_button.clicked.connect(self.load_entities)
        self.analyze_button.clicked.connect(self.run_analysis)

        buttons = QHBoxLayout()
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.analyze_button)
        buttons.addStretch()
        grid.addLayout(buttons, 2, 0, 1, 6)
        root.addWidget(frame)

        cards = QHBoxLayout()
        self.opens_card = self._card("Open", "0")
        self.avg_size_card = self._card("Ort. Open Size", "0.00x")
        self.wwsf_card = self._card("WWSF", "0.00%")
        self.wsd_card = self._card("W$SD", "0.00%")
        self.pattern_card = self._card("En Sık Kalıp", "—")
        for card in (
            self.opens_card, self.avg_size_card, self.wwsf_card,
            self.wsd_card, self.pattern_card,
        ):
            cards.addWidget(card)
        root.addLayout(cards)

        self.compare_label = QLabel("")
        self.compare_label.setObjectName("OpenSizeCompare")
        self.compare_label.setWordWrap(True)
        self.compare_label.hide()
        root.addWidget(self.compare_label)

        self.status_label = QLabel("Filtreleri seçip analizi başlat.")
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(14)
        self.table.setHorizontalHeaderLabels([
            "Pozisyon", "Open Size", "Open", "Dağılım %", "Ort. Size",
            "Ort. Stack", "3Bet Faced", "Flop Seen", "Pot Won", "WWSF",
            "WWSF Sample", "W$SD", "W$SD Sample", "Gözlenen Kalıp",
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        for i in range(13):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(13, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        warning = QLabel(
            "Kalıp açıklaması kesin niyet okuması değildir. "
            "WWSF flop gören opener, W$SD kart gösteren opener üzerinden hesaplanır."
        )
        warning.setObjectName("PageSubtitle")
        warning.setWordWrap(True)
        root.addWidget(warning)

        self.setStyleSheet("""
            QFrame#OpenSizeFilters {
                background:#171b24; border:1px solid #303744; border-radius:12px;
            }
            QFrame#OpenSizeCard {
                background:#1d222d; border:1px solid #343b49; border-radius:11px;
            }
            QLabel#OpenSizeCardTitle { color:#9ca3af; font-size:12px; }
            QLabel#OpenSizeCardValue { font-size:21px; font-weight:800; }
            QLabel#OpenSizeCompare {
                padding:14px; background:#23262d; border:1px solid #3b4658;
                border-radius:10px; font-size:14px; font-weight:700;
            }
        """)

    def _card(self, title: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("OpenSizeCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 11, 15, 11)
        title_label = QLabel(title)
        title_label.setObjectName("OpenSizeCardTitle")
        value_label = QLabel(value)
        value_label.setObjectName("OpenSizeCardValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
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
                    "SELECT DISTINCT site FROM hands WHERE site IS NOT NULL AND site <> '' ORDER BY site"
                ).fetchall()
                stakes = con.execute(
                    "SELECT DISTINCT stakes FROM hands WHERE stakes IS NOT NULL AND stakes <> '' ORDER BY stakes"
                ).fetchall()
            for row in sites:
                self.site_combo.addItem(str(row[0]), str(row[0]))
            for row in stakes:
                self.stakes_combo.addItem(str(row[0]), str(row[0]))
            self.filters_loaded = True
        except Exception as exc:
            QMessageBox.critical(self, "Filtre Hatası", f"{type(exc).__name__}: {exc}")

    def _mode_changed(self) -> None:
        mode = str(self.mode_combo.currentData())
        self.entity_combo.setEnabled(mode != "POOL")
        if mode == "POOL":
            self.entity_combo.clear()

    def load_entities(self) -> None:
        mode = str(self.mode_combo.currentData())
        if mode == "POOL":
            QMessageBox.information(self, "Open Size Explorer", "Pool modunda profil seçilmez.")
            return
        try:
            entities = self.service.available_entities(
                mode=mode,
                site=str(self.site_combo.currentData() or ""),
                stakes=str(self.stakes_combo.currentData() or ""),
            )
            self.entity_combo.clear()
            for name, hands in entities:
                self.entity_combo.addItem(f"{name} ({hands:,} hands)", name)
            self.status_label.setText(f"{len(entities)} profil yüklendi.")
        except Exception as exc:
            QMessageBox.critical(self, "Profil Hatası", f"{type(exc).__name__}: {exc}")

    def run_analysis(self) -> None:
        if self.worker_thread is not None:
            return

        mode = str(self.mode_combo.currentData())
        entity_name = str(self.entity_combo.currentData() or "")
        if mode != "POOL" and not entity_name:
            QMessageBox.information(self, "Open Size Explorer", "Önce profil yükleyip seç.")
            return

        self.analyze_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self.status_label.setText("Open size analizi hesaplanıyor…")

        self.worker_thread = QThread(self)
        self.worker = OpenSizeWorker(
            self.database_path,
            mode,
            entity_name,
            str(self.site_combo.currentData() or ""),
            str(self.stakes_combo.currentData() or ""),
            str(self.position_combo.currentData() or ""),
            self.minimum_sample.value(),
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._analysis_finished)
        self.worker.failed.connect(self._analysis_failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    @Slot(dict)
    def _analysis_finished(self, result: dict[str, Any]) -> None:
        entity = result.get("entity", {})
        pool = result.get("pool", {})
        rows = entity.get("rows", [])
        self._fill_table(rows)

        self.opens_card.value_label.setText(f"{int(entity.get('opens', 0)):,}".replace(",", "."))
        self.avg_size_card.value_label.setText(f"{float(entity.get('avg_size_bb', 0)):.2f}x")
        self.wwsf_card.value_label.setText(f"{float(entity.get('wwsf', 0)):.2f}%")
        self.wsd_card.value_label.setText(f"{float(entity.get('wsd', 0)):.2f}%")

        if rows:
            top = max(rows, key=lambda row: row["opens"])
            self.pattern_card.value_label.setText(f"{top['position']} {top['size_bucket']}")
        else:
            self.pattern_card.value_label.setText("—")

        if pool:
            self.compare_label.show()
            self.compare_label.setText(
                "Alias vs Pool — "
                f"Ort. Size Δ {float(entity.get('avg_size_bb', 0)) - float(pool.get('avg_size_bb', 0)):+.2f}x | "
                f"WWSF Δ {float(entity.get('wwsf', 0)) - float(pool.get('wwsf', 0)):+.2f} | "
                f"W$SD Δ {float(entity.get('wsd', 0)) - float(pool.get('wsd', 0)):+.2f}"
            )
        else:
            self.compare_label.hide()

        self.status_label.setText(
            f"{int(entity.get('opens', 0)):,} open analiz edildi; {len(rows)} grup gösteriliyor."
        )

    def _fill_table(self, rows: list[dict[str, Any]]) -> None:
        self.table.setUpdatesEnabled(False)
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(rows))

        for r, row in enumerate(rows):
            values = [
                row["position"], row["size_bucket"], str(row["opens"]),
                f"{row['share']:.2f}",
                "—" if row["avg_size_bb"] is None else f"{row['avg_size_bb']:.2f}x",
                "—" if row["avg_stack_bb"] is None else f"{row['avg_stack_bb']:.1f}bb",
                f"{row['three_bet_faced']:.2f}", f"{row['flop_seen']:.2f}",
                f"{row['pot_won']:.2f}", f"{row['wwsf']:.2f}",
                str(row["wwsf_sample"]), f"{row['wsd']:.2f}",
                str(row["wsd_sample"]), row["pattern_note"],
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if 2 <= c <= 12:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, item)

        self.table.setSortingEnabled(True)
        self.table.setUpdatesEnabled(True)

    @Slot(str)
    def _analysis_failed(self, message: str) -> None:
        QMessageBox.critical(self, "Open Size Analiz Hatası", message)
        self.status_label.setText("Analiz başarısız.")

    def _cleanup_worker(self) -> None:
        self.analyze_button.setEnabled(True)
        self.load_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
