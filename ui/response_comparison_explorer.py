from __future__ import annotations

from typing import Any
import threading
import time

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QProgressBar, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from services.response_comparison_service import ResponseComparisonService


class ResponseComparisonWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)
    progress = Signal(dict)

    def __init__(self, database_path: str, arguments: dict[str, Any]) -> None:
        super().__init__()
        self.service = ResponseComparisonService(database_path)
        self.arguments = arguments
        self._cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(
                self.service.analyze(
                    **self.arguments,
                    progress_callback=self.progress.emit,
                    should_cancel=self._cancel_event.is_set,
                )
            )
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    def cancel(self) -> None:
        self._cancel_event.set()


class ResponseComparisonExplorer(QWidget):
    COLUMNS = [
        ("position", "Pozisyon"), ("open_size", "Open Size"),
        ("board", "Board"), ("spot", "Street / Bet Size"),
        ("bot_fold", "Fold vs Bot"), ("pool_fold", "Fold vs Pool"),
        ("pressure_edge", "Pressure Edge"),
        ("bot_call", "Call vs Bot"), ("pool_call", "Call vs Pool"),
        ("call_edge", "Call Δ"), ("bot_raise", "Raise vs Bot"),
        ("pool_raise", "Raise vs Pool"), ("raise_edge", "Raise Δ"),
        ("bot_sample", "Bot Smp"), ("pool_sample", "Pool Smp"),
        ("confidence", "Güven"), ("priority", "Öncelik"),
        ("finding", "Bulgular"),
    ]

    def __init__(self, database_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.database_path = database_path
        self.service = ResponseComparisonService(database_path)
        self.worker_thread: QThread | None = None
        self.worker: ResponseComparisonWorker | None = None
        self._analysis_started_at = 0.0
        self._build_ui()
        QTimer.singleShot(100, self.refresh_filters)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(12)

        title = QLabel("Response Comparison Engine V4")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "İlk çalıştırmada eksik eller küçük paketlerle indekslenir. "
            "Sonraki karşılaştırmalar response_nodes üzerinden hızlı çalışır."
        )
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        grid = QGridLayout(filters)
        grid.setContentsMargins(14, 14, 14, 14)

        self.group_combo = QComboBox()
        self.node_combo = QComboBox()
        self.site_combo = QComboBox()
        self.stakes_combo = QComboBox()
        self.position_combo = QComboBox()
        self.minimum_sample = QSpinBox()
        self.minimum_sample.setRange(10, 1_000_000)
        self.minimum_sample.setValue(50)
        self.minimum_sample.setSingleStep(25)

        for key, label in self.service.nodes():
            self.node_combo.addItem(label, key)
        self.site_combo.addItem("Tüm Siteler", "")
        self.stakes_combo.addItem("Tüm Limitler", "")
        for label, value in [
            ("Tüm Pozisyonlar", ""), ("UTG", "UTG"), ("UTG+1", "UTG+1"),
            ("HJ", "HJ"), ("CO", "CO"), ("BTN", "BTN"),
            ("SB", "SB"), ("BB", "BB"),
        ]:
            self.position_combo.addItem(label, value)

        widgets = [
            ("Bot Group", self.group_combo), ("Node", self.node_combo),
            ("Site", self.site_combo), ("Stakes", self.stakes_combo),
            ("Pozisyon", self.position_combo), ("Min Sample", self.minimum_sample),
        ]
        for column, (label, widget) in enumerate(widgets):
            grid.addWidget(QLabel(label), 0, column)
            grid.addWidget(widget, 1, column)

        self.analyze_button = QPushButton("Bot vs Pool Karşılaştır")
        self.analyze_button.clicked.connect(self.run_analysis)
        grid.addWidget(self.analyze_button, 1, len(widgets))
        self.cancel_button = QPushButton("Durdur")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_analysis)
        grid.addWidget(self.cancel_button, 1, len(widgets) + 1)
        root.addWidget(filters)

        self.summary_label = QLabel("Filtreleri seçip analizi başlat.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setObjectName("ResponseSummary")
        root.addWidget(self.summary_label)

        self.status_label = QLabel("")
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        root.addWidget(self.progress_bar)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _key, label in self.COLUMNS])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for index in range(len(self.COLUMNS) - 1):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(self.COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        self.site_combo.currentIndexChanged.connect(self._reload_stakes)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(100, self.refresh_filters)

    def refresh_filters(self) -> None:
        try:
            selected_group = self.group_combo.currentData()
            self.group_combo.clear()
            for name, hands in self.service.groups():
                self.group_combo.addItem(f"{name} ({hands:,} hands)", name)
            if selected_group:
                index = self.group_combo.findData(selected_group)
                if index >= 0:
                    self.group_combo.setCurrentIndex(index)

            selected_site = self.site_combo.currentData()
            self.site_combo.blockSignals(True)
            self.site_combo.clear()
            self.site_combo.addItem("Tüm Siteler", "")
            for site in self.service.sites():
                self.site_combo.addItem(site, site)
            if selected_site:
                index = self.site_combo.findData(selected_site)
                if index >= 0:
                    self.site_combo.setCurrentIndex(index)
            self.site_combo.blockSignals(False)
            self._reload_stakes()

            status = self.service.index_status()
            self.status_label.setText(
                f"{self.group_combo.count()} bot grubu • "
                f"indeks {status['indexed']:,}/{status['total']:,} el • "
                f"{status['nodes']:,} node"
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "Response Filtre Hatası", f"{type(exc).__name__}: {exc}"
            )

    def _reload_stakes(self) -> None:
        selected = self.stakes_combo.currentData()
        self.stakes_combo.clear()
        self.stakes_combo.addItem("Tüm Limitler", "")
        for stakes in self.service.stakes(str(self.site_combo.currentData() or "")):
            self.stakes_combo.addItem(stakes, stakes)
        if selected:
            index = self.stakes_combo.findData(selected)
            if index >= 0:
                self.stakes_combo.setCurrentIndex(index)

    def run_analysis(self) -> None:
        if self.worker_thread is not None:
            return
        bot_group = str(self.group_combo.currentData() or "")
        if not bot_group:
            QMessageBox.information(self, "Response Comparison", "Önce bir Bot Group seç.")
            return

        arguments = {
            "bot_group": bot_group,
            "node": str(self.node_combo.currentData() or "ALL_RESPONSES"),
            "site": str(self.site_combo.currentData() or ""),
            "stakes": str(self.stakes_combo.currentData() or ""),
            "position": str(self.position_combo.currentData() or ""),
            "minimum_sample": int(self.minimum_sample.value()),
        }
        self.analyze_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._analysis_started_at = time.monotonic()
        self.progress_bar.setValue(0)
        self.status_label.setText(
            "Eksik eller küçük paketlerle indeksleniyor; ardından karşılaştırma yapılacak…"
        )
        self.worker_thread = QThread(self)
        self.worker = ResponseComparisonWorker(self.database_path, arguments)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._analysis_finished)
        self.worker.failed.connect(self._analysis_failed)
        self.worker.progress.connect(self._analysis_progress)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)
        self.worker_thread.start()

    def cancel_analysis(self) -> None:
        if self.worker is None:
            return
        self.worker.cancel()
        self.cancel_button.setEnabled(False)
        self.status_label.setText(
            "Durdurma isteği alındı; aktif batch güvenle tamamlanıyor…"
        )

    @Slot(dict)
    def _analysis_progress(self, progress: dict[str, Any]) -> None:
        phase = str(progress.get("phase") or "index")
        if phase == "comparison":
            self.progress_bar.setValue(1000)
            self.status_label.setText(
                "İndeks hazır; bot/pool karşılaştırması yapılıyor…"
            )
            return

        completed = int(progress.get("completed", 0) or 0)
        pending = int(progress.get("pending", 0) or 0)
        indexed = int(progress.get("indexed", 0) or 0)
        added_nodes = int(progress.get("added_nodes", 0) or 0)
        fraction = completed / pending if pending else 1.0
        self.progress_bar.setValue(min(1000, int(fraction * 1000)))

        elapsed = max(0.001, time.monotonic() - self._analysis_started_at)
        rate = completed / elapsed
        remaining = max(0, pending - completed)
        eta_seconds = int(remaining / rate) if rate > 0 else 0
        eta_minutes, eta_remainder = divmod(eta_seconds, 60)
        eta_hours, eta_minutes = divmod(eta_minutes, 60)
        eta_text = (
            f"{eta_hours:02d}:{eta_minutes:02d}:{eta_remainder:02d}"
            if eta_hours
            else f"{eta_minutes:02d}:{eta_remainder:02d}"
        )
        self.status_label.setText(
            f"Bu çalışmada {completed:,}/{pending:,} el • "
            f"toplam indeks {indexed:,} • {rate:,.0f} el/sn • "
            f"+{added_nodes:,} node • ETA {eta_text}"
        )

    @Slot(dict)
    def _analysis_finished(self, result: dict[str, Any]) -> None:
        rows = result.get("rows", [])
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        percent_keys = {
            "bot_fold", "pool_fold", "pressure_edge",
            "bot_call", "pool_call", "call_edge",
            "bot_raise", "pool_raise", "raise_edge",
        }
        for row_index, row in enumerate(rows):
            for column_index, (key, _label) in enumerate(self.COLUMNS):
                value = row.get(key, "")
                if key in percent_keys and isinstance(value, (int, float)):
                    prefix = "+" if key.endswith("edge") and value > 0 else ""
                    text = f"{prefix}{value:.1f}%"
                elif key == "priority" and isinstance(value, (int, float)):
                    text = f"{value:.2f}"
                elif isinstance(value, int):
                    text = f"{value:,}"
                else:
                    text = str(value)
                item = QTableWidgetItem(text)
                if isinstance(value, (int, float)):
                    item.setData(Qt.ItemDataRole.UserRole, float(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_index, column_index, item)

        self.table.setSortingEnabled(True)
        self.summary_label.setText(str(result.get("summary", "")))
        index = result.get("index", {})
        self.status_label.setText(
            f"{len(rows)} spot • indeks {index.get('indexed', 0):,}/"
            f"{index.get('total', 0):,} el • "
            f"bu çalışmada +{index.get('added_hands', 0):,} el, "
            f"+{index.get('added_nodes', 0):,} node"
        )
        self.analyze_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    @Slot(str)
    def _analysis_failed(self, message: str) -> None:
        self.analyze_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.status_label.setText("Analiz başarısız.")
        QMessageBox.critical(self, "Response Comparison Hatası", message)

    @Slot()
    def _cleanup_worker(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
        self.worker = None
        self.worker_thread = None
