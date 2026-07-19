from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
    QTextEdit, QVBoxLayout, QWidget,
)

from services.experiment_database_service import ExperimentDatabaseService


class ExperimentDatabaseManager(QWidget):
    def __init__(self, main_database_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.main_database_path = main_database_path
        self.service = ExperimentDatabaseService(main_database_path)
        self._build_ui()
        QTimer.singleShot(100, self.refresh_all)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(13)

        title = QLabel("Experiment Database Manager v1")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Adaptasyon deneylerini ana MDA database'inden ayrı tutar. "
            "Varsayılan blok boyutu 5.000 hero elidir."
        )
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        frame = QFrame()
        frame.setObjectName("ExperimentFrame")
        grid = QGridLayout(frame)
        grid.setContentsMargins(15, 15, 15, 15)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("BTN_CO_Large_Open_01")
        self.hero_edit = QLineEdit()
        self.hero_edit.setPlaceholderText("Kendi nickin")

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")
        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(date.today())
        self.start_date.setDisplayFormat("yyyy-MM-dd")

        self.block_size = QSpinBox()
        self.block_size.setRange(500, 100000)
        self.block_size.setValue(5000)
        self.block_size.setSingleStep(500)

        labels = ["Deney Adı", "Hero Nick", "Site", "Stakes", "Başlangıç", "Blok"]
        widgets = [
            self.name_edit, self.hero_edit, self.site_combo,
            self.stakes_combo, self.start_date, self.block_size,
        ]
        for index, (label, widget) in enumerate(zip(labels, widgets)):
            grid.addWidget(QLabel(label), 0, index)
            grid.addWidget(widget, 1, index)

        self.create_button = QPushButton("Yeni Deney Oluştur")
        self.create_button.clicked.connect(self.create_experiment)
        grid.addWidget(self.create_button, 2, 0, 1, 2)
        root.addWidget(frame)

        manage = QFrame()
        manage.setObjectName("ExperimentFrame")
        manage_layout = QHBoxLayout(manage)
        manage_layout.setContentsMargins(15, 15, 15, 15)

        self.experiment_combo = QComboBox()
        self.experiment_combo.setMinimumWidth(360)
        self.experiment_combo.currentIndexChanged.connect(self.load_stats)

        self.sync_button = QPushButton("Ana Database'den Senkronla")
        self.sync_button.clicked.connect(self.sync_selected)
        self.refresh_button = QPushButton("Yenile")
        self.refresh_button.clicked.connect(self.refresh_all)

        manage_layout.addWidget(QLabel("Aktif Deney"))
        manage_layout.addWidget(self.experiment_combo, 1)
        manage_layout.addWidget(self.sync_button)
        manage_layout.addWidget(self.refresh_button)
        root.addWidget(manage)

        cards = QHBoxLayout()
        self.total_card = self._card("Hero Hands", "0")
        self.blocks_card = self._card("Tamamlanan Blok", "0")
        self.current_card = self._card("Aktif Blok", "0 / 5.000")
        self.path_card = self._card("Database", "—")
        for card in (self.total_card, self.blocks_card, self.current_card, self.path_card):
            cards.addWidget(card)
        root.addLayout(cards)

        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        root.addWidget(self.info_text, 1)

        warning = QLabel(
            "Her session/gün sonunda elleri önce normal Import ekranından ana database'e ekle. "
            "Sonra bu ekranda senkronla. Aynı hand_id tekrar eklenmez."
        )
        warning.setObjectName("PageSubtitle")
        warning.setWordWrap(True)
        root.addWidget(warning)

        self.setStyleSheet("""
            QFrame#ExperimentFrame {
                background:#171b24; border:1px solid #303744; border-radius:12px;
            }
            QFrame#ExperimentCard {
                background:#1d222d; border:1px solid #343b49; border-radius:11px;
            }
            QLabel#ExperimentCardTitle { color:#9ca3af; font-size:12px; }
            QLabel#ExperimentCardValue { font-size:18px; font-weight:800; }
            QTextEdit {
                background:#11151d; border:1px solid #303744;
                border-radius:8px; padding:10px;
            }
        """)

    def _card(self, title: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("ExperimentCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(15, 11, 15, 11)
        title_label = QLabel(title)
        title_label.setObjectName("ExperimentCardTitle")
        value_label = QLabel(value)
        value_label.setObjectName("ExperimentCardValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_label.setWordWrap(True)
        frame.value_label = value_label
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        return frame

    def refresh_all(self) -> None:
        self.refresh_filters()
        self.refresh_experiments()

    def refresh_filters(self) -> None:
        try:
            import duckdb
            with duckdb.connect(self.main_database_path, read_only=True) as con:
                sites = con.execute(
                    "SELECT DISTINCT TRIM(site) FROM hands "
                    "WHERE site IS NOT NULL AND TRIM(site)<>'' ORDER BY 1"
                ).fetchall()
                stakes = con.execute(
                    "SELECT DISTINCT TRIM(stakes) FROM hands "
                    "WHERE stakes IS NOT NULL AND TRIM(stakes)<>'' ORDER BY 1"
                ).fetchall()

            self.site_combo.clear()
            self.site_combo.addItem("Tüm Siteler", "")
            for row in sites:
                self.site_combo.addItem(str(row[0]), str(row[0]))

            self.stakes_combo.clear()
            self.stakes_combo.addItem("Tüm Limitler", "")
            for row in stakes:
                self.stakes_combo.addItem(str(row[0]), str(row[0]))
        except Exception as exc:
            QMessageBox.critical(self, "Filtre Hatası", f"{type(exc).__name__}: {exc}")

    def refresh_experiments(self) -> None:
        current = self.experiment_combo.currentData()
        self.experiment_combo.blockSignals(True)
        self.experiment_combo.clear()
        for row in self.service.list_experiments():
            self.experiment_combo.addItem(
                f"{row['name']} — {row['hero_name']}",
                row["name"],
            )
        self.experiment_combo.blockSignals(False)
        index = self.experiment_combo.findData(current)
        if index >= 0:
            self.experiment_combo.setCurrentIndex(index)
        self.load_stats()

    def create_experiment(self) -> None:
        try:
            row = self.service.create_experiment(
                name=self.name_edit.text(),
                hero_name=self.hero_edit.text(),
                site=str(self.site_combo.currentData() or ""),
                stakes=str(self.stakes_combo.currentData() or ""),
                start_date=self.start_date.date().toString("yyyy-MM-dd"),
                block_size=self.block_size.value(),
            )
            self.info_text.setPlainText(
                "DENEY OLUŞTURULDU\n" + "=" * 60 + "\n"
                f"Ad: {row['name']}\nHero: {row['hero_name']}\n"
                f"Site: {row['site'] or 'ALL'}\nStakes: {row['stakes'] or 'ALL'}\n"
                f"Başlangıç: {row['start_date']}\nBlok: {row['block_size']:,}\n"
                f"Database: {row['database_path']}"
            )
            self.refresh_experiments()
            index = self.experiment_combo.findData(row["name"])
            if index >= 0:
                self.experiment_combo.setCurrentIndex(index)
        except Exception as exc:
            QMessageBox.critical(self, "Deney Hatası", f"{type(exc).__name__}: {exc}")

    def sync_selected(self) -> None:
        name = str(self.experiment_combo.currentData() or "")
        if not name:
            QMessageBox.information(self, "Experiment Manager", "Önce deney oluştur veya seç.")
            return

        self.sync_button.setEnabled(False)
        self.sync_button.setText("Senkronlanıyor...")
        try:
            row = self.service.sync_experiment(name)
            self.info_text.setPlainText(
                "SENKRON TAMAMLANDI\n" + "=" * 60 + "\n"
                f"Deney: {row['experiment_name']}\n"
                f"Filtreye uyan ana DB eli: {row['selected_hands']:,}\n"
                f"Yeni eklenen: {row['new_hands']:,}\n"
                f"Deney DB toplam: {row['total_hands']:,}\n"
                f"Hero hands: {row['hero_hands']:,}\n"
                f"Database: {row['database_path']}"
            )
            self.load_stats()
        except Exception as exc:
            QMessageBox.critical(self, "Senkron Hatası", f"{type(exc).__name__}: {exc}")
        finally:
            self.sync_button.setEnabled(True)
            self.sync_button.setText("Ana Database'den Senkronla")

    def load_stats(self) -> None:
        name = str(self.experiment_combo.currentData() or "")
        if not name:
            self.total_card.value_label.setText("0")
            self.blocks_card.value_label.setText("0")
            self.current_card.value_label.setText("0 / 5.000")
            self.path_card.value_label.setText("—")
            return
        try:
            record = self.service.get_experiment(name)
            stats = self.service.experiment_stats(name)
            block = int(stats["block_size"])
            self.total_card.value_label.setText(
                f"{int(stats['hero_hands']):,}".replace(",", ".")
            )
            self.blocks_card.value_label.setText(str(int(stats["completed_blocks"])))
            self.current_card.value_label.setText(
                f"{int(stats['current_block_hands']):,} / {block:,}".replace(",", ".")
            )
            self.path_card.value_label.setText(Path(record["database_path"]).name)
        except Exception as exc:
            QMessageBox.critical(self, "Bilgi Hatası", f"{type(exc).__name__}: {exc}")
