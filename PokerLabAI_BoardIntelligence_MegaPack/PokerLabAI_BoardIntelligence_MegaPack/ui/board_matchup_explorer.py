from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from services.board_matchup_service import BoardMatchupService
from services.gto_reference_service import GTOReferenceService


class BoardMatchupWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, database_path: str, arguments: dict[str, Any]) -> None:
        super().__init__()
        self.service = BoardMatchupService(database_path)
        self.gto_service = GTOReferenceService()
        self.arguments = arguments

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(self.service.analyze(**self.arguments))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class BoardMatchupExplorer(QWidget):
    COLUMNS = [
        ("board_family", "Board Ailesi"), ("street", "Street"),
        ("bot_cbet", "Bot CBet"), ("human_cbet", "Human CBet"), ("cbet_delta", "CBet Δ"),
        ("human_fold", "Human Fold vs Bot"), ("human_call", "Call"), ("human_raise", "Raise"),
        ("bot_avg_size", "Bot Avg Size"), ("human_avg_size", "Human Avg Size"),
        ("bot_overbet", "Bot Overbet"), ("human_overbet", "Human Overbet"),
        ("human_fold_vs_overbet", "Fold vs Bot OB"),
        ("bot_sample", "Bot Opp"), ("human_sample", "Human Opp"), ("response_sample", "Response N"),
        ("gto_bet", "GTO Bet"), ("bot_gto_delta", "Bot-GTO"), ("human_gto_delta", "Pool-GTO"),
        ("gto_fold", "GTO Fold"), ("fold_gto_delta", "Fold-GTO"),
        ("edge_score", "Edge"), ("confidence", "Güven"), ("insight", "Veri Yorumu"),
    ]

    def __init__(self, database_path: str = "database/pokerlab.duckdb") -> None:
        super().__init__()
        self.database_path = database_path
        self.service = BoardMatchupService(database_path)
        self.thread: QThread | None = None
        self.worker: BoardMatchupWorker | None = None
        self._build_ui()
        self.refresh_filters()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("Board Matchup & Pool Response")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        subtitle = QLabel(
            "Seçilen bot grubunun board bazlı c-betlerini, botlar hariç human pool c-betleri ve human cevaplarıyla karşılaştırır."
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: #9aa7b8;")
        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        grid = QGridLayout(filters)
        self.bot_group = QComboBox()
        self.site = QComboBox()
        self.stakes = QComboBox()
        self.position = QComboBox()
        self.position.addItems(["Tüm Pozisyonlar", "UTG", "MP", "HJ", "CO", "BTN", "SB", "BB"])
        self.minimum_sample = QSpinBox()
        self.minimum_sample.setRange(10, 1000000)
        self.minimum_sample.setValue(50)
        self.analyze_button = QPushButton("Bot vs Human Pool Analiz Et")
        self.save_gto_button = QPushButton("Tablodaki GTO'ları Kaydet")
        self.analyze_button.clicked.connect(self.run_analysis)
        self.save_gto_button.clicked.connect(self._save_gto)

        widgets = [
            ("Bot Grubu", self.bot_group), ("Site", self.site), ("Stakes", self.stakes),
            ("Pozisyon", self.position), ("Min Sample", self.minimum_sample),
        ]
        for col, (label, widget) in enumerate(widgets):
            grid.addWidget(QLabel(label), 0, col)
            grid.addWidget(widget, 1, col)
        grid.addWidget(self.analyze_button, 1, len(widgets))
        grid.addWidget(self.save_gto_button, 1, len(widgets) + 1)
        root.addWidget(filters)

        self.summary = QLabel("Filtreleri seçip analizi çalıştır.")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("padding: 10px; background: #111b2a; border: 1px solid #27364b; font-weight: 600;")
        root.addWidget(self.summary)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([label for _, label in self.COLUMNS])
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.site.currentTextChanged.connect(self._reload_stakes)

    def refresh_filters(self) -> None:
        try:
            current_group = self.bot_group.currentData()
            self.bot_group.clear()
            for name, hands in self.service.bot_groups():
                self.bot_group.addItem(f"{name} ({hands:,} hands)", name)
            if current_group:
                index = self.bot_group.findData(current_group)
                if index >= 0:
                    self.bot_group.setCurrentIndex(index)

            current_site = self.site.currentData()
            self.site.blockSignals(True)
            self.site.clear()
            self.site.addItem("Tüm Siteler", "")
            for site in self.service.sites():
                self.site.addItem(site, site)
            if current_site:
                index = self.site.findData(current_site)
                if index >= 0:
                    self.site.setCurrentIndex(index)
            self.site.blockSignals(False)
            self._reload_stakes()
        except Exception as exc:
            self.summary.setText(f"Filtre yükleme hatası: {type(exc).__name__}: {exc}")

    def _reload_stakes(self) -> None:
        current = self.stakes.currentData()
        self.stakes.clear()
        self.stakes.addItem("Tüm Limitler", "")
        try:
            for stake in self.service.stakes(str(self.site.currentData() or "")):
                self.stakes.addItem(stake, stake)
            if current:
                index = self.stakes.findData(current)
                if index >= 0:
                    self.stakes.setCurrentIndex(index)
        except Exception:
            pass

    @Slot()
    def run_analysis(self) -> None:
        if self.thread is not None:
            return
        bot_group = str(self.bot_group.currentData() or "")
        if not bot_group:
            QMessageBox.warning(self, "Board Matchup", "Önce bir bot grubu seç.")
            return
        args = {
            "bot_group": bot_group,
            "site": str(self.site.currentData() or ""),
            "stakes": str(self.stakes.currentData() or ""),
            "position": "" if self.position.currentIndex() == 0 else self.position.currentText(),
            "minimum_sample": int(self.minimum_sample.value()),
        }
        self.analyze_button.setEnabled(False)
        self.analyze_button.setText("Analiz çalışıyor...")
        self.summary.setText("Bot ve human pool board cevapları hesaplanıyor...")
        self.thread = QThread(self)
        self.worker = BoardMatchupWorker(self.database_path, args)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._analysis_finished)
        self.worker.failed.connect(self._analysis_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self._thread_finished)
        self.thread.start()

    @Slot(dict)
    def _analysis_finished(self, result: dict) -> None:
        rows = list(result.get("rows") or [])
        site = str(self.site.currentData() or "")
        stakes = str(self.stakes.currentData() or "")
        for row in rows:
            family = str(row.get("board_family") or "ALL")
            street = str(row.get("street") or "")
            gto_bet = self.gto_service.get(site, stakes, family, street, "BET")
            gto_fold = self.gto_service.get(site, stakes, family, street, "FOLD")
            row["gto_bet"] = gto_bet
            row["gto_fold"] = gto_fold
            row["bot_gto_delta"] = None if gto_bet is None else float(row.get("bot_cbet") or 0) - gto_bet
            row["human_gto_delta"] = None if gto_bet is None else float(row.get("human_cbet") or 0) - gto_bet
            row["fold_gto_delta"] = None if gto_fold is None else float(row.get("human_fold") or 0) - gto_fold
        self.summary.setText(str(result.get("summary") or "") + " GTO Bet/Fold kolonları düzenlenebilir ve kalıcı kaydedilir.")
        self._fill_table(rows)

    @Slot(str)
    def _analysis_failed(self, message: str) -> None:
        self.summary.setText(message)
        QMessageBox.critical(self, "Board Matchup Hatası", message)

    @Slot()
    def _thread_finished(self) -> None:
        self.worker = None
        self.thread = None
        self.analyze_button.setEnabled(True)
        self.analyze_button.setText("Bot vs Human Pool Analiz Et")

    @Slot()
    def _save_gto(self) -> None:
        site = str(self.site.currentData() or "")
        stakes = str(self.stakes.currentData() or "")
        key_to_col = {key: idx for idx, (key, _) in enumerate(self.COLUMNS)}
        for row_idx in range(self.table.rowCount()):
            family_item = self.table.item(row_idx, key_to_col["board_family"])
            street_item = self.table.item(row_idx, key_to_col["street"])
            if not family_item or not street_item:
                continue
            family, street = family_item.text(), street_item.text()
            for metric, column_key in (("BET", "gto_bet"), ("FOLD", "gto_fold")):
                item = self.table.item(row_idx, key_to_col[column_key])
                text = item.text().strip().replace("%", "").replace(",", ".") if item else ""
                value = None
                if text:
                    try:
                        value = float(text)
                    except ValueError:
                        QMessageBox.warning(self, "GTO", f"{family} / {street}: GTO değeri sayı olmalı.")
                        return
                self.gto_service.set(site, stakes, family, street, metric, value)
        self.summary.setText("GTO Bet ve GTO Fold referansları kaydedildi. Sapmaları yenilemek için analizi tekrar çalıştır.")

    def _fill_table(self, rows: list[dict[str, Any]]) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        pct_keys = {
            "bot_cbet", "human_cbet", "cbet_delta", "human_fold", "human_call", "human_raise",
            "bot_avg_size", "human_avg_size", "bot_overbet", "human_overbet", "human_fold_vs_overbet",
            "gto_bet", "bot_gto_delta", "human_gto_delta", "gto_fold", "fold_gto_delta",
        }
        int_keys = {"bot_sample", "human_sample", "response_sample", "edge_score"}
        for row_idx, row in enumerate(rows):
            for col_idx, (key, _) in enumerate(self.COLUMNS):
                value = row.get(key, "")
                if key in pct_keys:
                    text = "" if value is None else f"{float(value):.1f}%"
                elif key in int_keys:
                    text = f"{int(value or 0):,}"
                else:
                    text = str(value)
                item = QTableWidgetItem(text)
                if key in pct_keys:
                    item.setData(Qt.ItemDataRole.UserRole, float(value or 0))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if key not in {"gto_bet", "gto_fold"}:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                elif key in int_keys:
                    item.setData(Qt.ItemDataRole.UserRole, int(value or 0))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)
        self.table.setSortingEnabled(True)
        self.table.resizeRowsToContents()
