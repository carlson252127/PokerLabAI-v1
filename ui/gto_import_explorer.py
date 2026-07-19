from __future__ import annotations

import csv
import io
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.gto_comparison_service import GTOComparisonService
from services.spot_engine import SpotEngine


class GTOImportExplorer(QWidget):
    POSITIONS = ["BTN", "CO", "HJ", "UTG", "SB", "BB"]

    ALIASES = {
        "vpip": "vpip",
        "pfr": "pfr",
        "3bet": "three_bet",
        "three bet": "three_bet",
        "flop pfr cbet": "flop_pfr_cbet",
        "flop cbet": "flop_pfr_cbet",
        "cbet flop": "flop_pfr_cbet",
        "turn pfr barrel": "turn_pfr_barrel",
        "turn barrel": "turn_pfr_barrel",
        "river pfr barrel": "river_pfr_barrel",
        "river barrel": "river_pfr_barrel",
        "flop fold vs bet": "flop_fold_vs_bet",
        "fold flop": "flop_fold_vs_bet",
        "turn fold vs bet": "turn_fold_vs_bet",
        "fold turn": "turn_fold_vs_bet",
        "river fold vs bet": "river_fold_vs_bet",
        "fold river": "river_fold_vs_bet",
        "flop check-raise": "flop_check_raise",
        "flop xr": "flop_check_raise",
        "xr flop": "flop_check_raise",
        "turn check-raise": "turn_check_raise",
        "turn xr": "turn_check_raise",
        "river check-raise": "river_check_raise",
        "river xr": "river_check_raise",
        "flop donk": "flop_donk",
        "turn probe": "turn_probe",
        "probe turn": "turn_probe",
        "river bet": "river_bet",
        "bet river": "river_bet",
    }

    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = database_path
        self.service = GTOComparisonService(database_path)
        self.filters_loaded = False
        self.parsed_rows: list[dict] = []

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("GTO Import")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Solver ekranından çıkardığın değerleri veya CSV verisini "
            "seçili spot için toplu kaydet."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filter_frame = QFrame()
        filter_frame.setObjectName("ImportFilters")

        grid = QGridLayout(filter_frame)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")

        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.hero_combo = QComboBox()
        self.hero_combo.addItem("Tüm Pozisyonlar", "")
        for position in self.POSITIONS:
            self.hero_combo.addItem(position, position)

        self.villain_combo = QComboBox()
        self.villain_combo.addItem("Tüm Rakip Poz.", "")
        for position in self.POSITIONS:
            self.villain_combo.addItem(position, position)

        self.location_combo = QComboBox()
        self.location_combo.addItem("IP + OOP", "")
        self.location_combo.addItem("IP", "IP")
        self.location_combo.addItem("OOP", "OOP")

        self.pot_type_combo = QComboBox()
        self.pot_type_combo.addItem("Tüm Potlar", "")
        self.pot_type_combo.addItem("SRP", "SRP")
        self.pot_type_combo.addItem("3Bet Pot", "3BET")
        self.pot_type_combo.addItem("4Bet+ Pot", "4BET")
        self.pot_type_combo.addItem("Limp Pot", "LIMP")

        self.texture_combo = QComboBox()
        self.texture_combo.addItem("Tüm Boardlar", "")
        self.texture_combo.addItem("A-High Rainbow", "A_HIGH_RAINBOW")
        self.texture_combo.addItem("A-High Two-Tone", "A_HIGH_TWO_TONE")
        self.texture_combo.addItem("A-High Monotone", "A_HIGH_MONOTONE")
        self.texture_combo.addItem("K-High Rainbow", "K_HIGH_RAINBOW")
        self.texture_combo.addItem("K-High Two-Tone", "K_HIGH_TWO_TONE")
        self.texture_combo.addItem("Q-High Rainbow", "Q_HIGH_RAINBOW")
        self.texture_combo.addItem("Low Rainbow", "LOW_RAINBOW")
        self.texture_combo.addItem("Low Two-Tone", "LOW_TWO_TONE")
        self.texture_combo.addItem("Paired", "PAIRED")
        self.texture_combo.addItem("Trips", "TRIPS")
        self.texture_combo.addItem("Connected", "CONNECTED")
        self.texture_combo.addItem("Rainbow", "RAINBOW")
        self.texture_combo.addItem("Two-Tone", "TWO_TONE")
        self.texture_combo.addItem("Monotone", "MONOTONE")

        labels = [
            "Site",
            "Stakes",
            "Hero Poz.",
            "Rakip Poz.",
            "Konum",
            "Pot Tipi",
            "Board Texture",
        ]

        widgets = [
            self.site_combo,
            self.stakes_combo,
            self.hero_combo,
            self.villain_combo,
            self.location_combo,
            self.pot_type_combo,
            self.texture_combo,
        ]

        for index, (label, widget) in enumerate(zip(labels, widgets)):
            grid.addWidget(QLabel(label), 0, index)
            grid.addWidget(widget, 1, index)

        root.addWidget(filter_frame)

        help_label = QLabel(
            "Kabul edilen örnek:\n"
            "Flop PFR CBet, 63.5\n"
            "Turn Barrel, 48.2\n"
            "River Bet, 39.1\n"
            "XR Flop, 13.4"
        )
        help_label.setObjectName("ImportHelp")
        help_label.setWordWrap(True)
        root.addWidget(help_label)

        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText(
            "Stat, GTO\n"
            "Flop PFR CBet, 63.5\n"
            "Turn Barrel, 48.2"
        )
        self.input_text.setMinimumHeight(150)
        root.addWidget(self.input_text)

        button_row = QHBoxLayout()

        self.parse_button = QPushButton("Metni Önizle")
        self.csv_button = QPushButton("CSV Aç")
        self.save_button = QPushButton("Tümünü Kaydet")
        self.clear_button = QPushButton("Temizle")

        self.parse_button.clicked.connect(self.parse_input)
        self.csv_button.clicked.connect(self.open_csv)
        self.save_button.clicked.connect(self.save_all)
        self.clear_button.clicked.connect(self.clear_all)

        button_row.addWidget(self.parse_button)
        button_row.addWidget(self.csv_button)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.clear_button)
        button_row.addStretch()

        root.addLayout(button_row)

        self.status_label = QLabel("Henüz veri ayrıştırılmadı.")
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            [
                "Girilen Stat",
                "Eşleşen Stat",
                "GTO %",
                "Durum",
            ]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        root.addWidget(self.table, 1)

        self.setStyleSheet(
            """
            QFrame#ImportFilters {
                background: #171b24;
                border: 1px solid #303744;
                border-radius: 12px;
            }

            QLabel#ImportHelp {
                padding: 14px 16px;
                background: #23262d;
                border: 1px solid #343944;
                border-radius: 10px;
                font-family: Consolas;
            }

            QTextEdit {
                background: #11151d;
                border: 1px solid #3a4252;
                border-radius: 8px;
                padding: 10px;
                font-family: Consolas;
            }
            """
        )

    def refresh_filters(self) -> None:
        if self.filters_loaded:
            return

        try:
            with self.service.connect() as con:
                sites = con.execute(
                    """
                    SELECT DISTINCT site
                    FROM hands
                    WHERE site IS NOT NULL AND site <> ''
                    ORDER BY site
                    """
                ).fetchall()

                stakes = con.execute(
                    """
                    SELECT DISTINCT stakes
                    FROM hands
                    WHERE stakes IS NOT NULL AND stakes <> ''
                    ORDER BY stakes
                    """
                ).fetchall()

            for row in sites:
                self.site_combo.addItem(str(row[0]), str(row[0]))

            for row in stakes:
                self.stakes_combo.addItem(str(row[0]), str(row[0]))

            self.filters_loaded = True

        except Exception as exc:
            QMessageBox.critical(
                self,
                "GTO Import Filtre Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def _normalize_name(self, text: str) -> str:
        return " ".join(
            text.lower()
            .replace("_", " ")
            .replace("-", " ")
            .split()
        )

    def _resolve_stat_key(self, name: str) -> str | None:
        normalized = self._normalize_name(name)

        if normalized in self.ALIASES:
            return self.ALIASES[normalized]

        for label, key in SpotEngine.SUPPORTED_STATS.items():
            if self._normalize_name(label) == normalized:
                return key

        return None

    def parse_input(self) -> None:
        text = self.input_text.toPlainText().strip()

        if not text:
            QMessageBox.information(
                self,
                "GTO Import",
                "Önce veri yapıştır.",
            )
            return

        self.parsed_rows = []

        for raw_line in text.splitlines():
            line = raw_line.strip()

            if not line:
                continue

            try:
                parsed = next(
                    csv.reader(
                        io.StringIO(line),
                        skipinitialspace=True,
                    )
                )
            except Exception:
                parsed = []

            if len(parsed) < 2:
                self.parsed_rows.append(
                    {
                        "raw_name": line,
                        "stat_key": None,
                        "stat_label": "",
                        "value": None,
                        "status": "Satır formatı hatalı",
                    }
                )
                continue

            name = parsed[0].strip()
            value_text = parsed[1].strip().replace("%", "").replace(",", ".")

            stat_key = self._resolve_stat_key(name)

            try:
                value = float(value_text)
            except ValueError:
                value = None

            stat_label = ""
            if stat_key:
                for label, key in SpotEngine.SUPPORTED_STATS.items():
                    if key == stat_key:
                        stat_label = label
                        break

            if stat_key is None:
                status = "Stat eşleşmedi"
            elif value is None:
                status = "Değer geçersiz"
            elif not 0 <= value <= 100:
                status = "0-100 dışında"
            else:
                status = "Hazır"

            self.parsed_rows.append(
                {
                    "raw_name": name,
                    "stat_key": stat_key,
                    "stat_label": stat_label,
                    "value": value,
                    "status": status,
                }
            )

        self._render_preview()

    def _render_preview(self) -> None:
        self.table.clearContents()
        self.table.setRowCount(len(self.parsed_rows))

        ready = 0

        for row_index, row in enumerate(self.parsed_rows):
            values = [
                row["raw_name"],
                row["stat_label"] or "—",
                (
                    "—"
                    if row["value"] is None
                    else f"{row['value']:.2f}"
                ),
                row["status"],
            ]

            for column_index, value in enumerate(values):
                self.table.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem(str(value)),
                )

            if row["status"] == "Hazır":
                ready += 1

        self.status_label.setText(
            f"{len(self.parsed_rows)} satır okundu; "
            f"{ready} satır kayda hazır."
        )

    def open_csv(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "GTO CSV Dosyası Seç",
            "",
            "CSV Files (*.csv);;Text Files (*.txt);;All Files (*.*)",
        )

        if not file_path:
            return

        try:
            text = Path(file_path).read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except OSError as exc:
            QMessageBox.critical(
                self,
                "CSV Hatası",
                str(exc),
            )
            return

        self.input_text.setPlainText(text)
        self.parse_input()

    def save_all(self) -> None:
        if not self.parsed_rows:
            self.parse_input()

        ready_rows = [
            row
            for row in self.parsed_rows
            if row["status"] == "Hazır"
        ]

        if not ready_rows:
            QMessageBox.information(
                self,
                "GTO Import",
                "Kayda hazır satır bulunamadı.",
            )
            return

        site = str(self.site_combo.currentData() or "ALL")
        stakes = str(self.stakes_combo.currentData() or "ALL")
        hero = str(self.hero_combo.currentData() or "ALL")
        villain = str(self.villain_combo.currentData() or "ALL")
        location = str(self.location_combo.currentData() or "ALL")
        pot_type = str(self.pot_type_combo.currentData() or "ALL")
        board_texture = str(
            self.texture_combo.currentData() or "ALL"
        )

        for row in ready_rows:
            self.service.save_baseline(
                site=site,
                stakes=stakes,
                hero_position=hero,
                villain_position=villain,
                location=location,
                pot_type=pot_type,
                board_texture=board_texture,
                stat_key=row["stat_key"],
                gto_value=float(row["value"]),
                note="GTO Import",
            )

        QMessageBox.information(
            self,
            "GTO Import Tamamlandı",
            f"{len(ready_rows)} GTO değeri kaydedildi.",
        )

        self.status_label.setText(
            f"{len(ready_rows)} değer kaydedildi."
        )

    def clear_all(self) -> None:
        self.input_text.clear()
        self.table.clearContents()
        self.table.setRowCount(0)
        self.parsed_rows = []
        self.status_label.setText("Temizlendi.")
