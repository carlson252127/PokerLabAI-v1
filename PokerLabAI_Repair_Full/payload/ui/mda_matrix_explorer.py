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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.gto_comparison_service import GTOComparisonService
from services.spot_engine import SpotEngine


class MDAMatrixWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        database_path: str,
        site: str,
        stakes: str,
        hero_position: str,
        villain_position: str,
        location: str,
        pot_type: str,
        board_texture: str,
    ) -> None:
        super().__init__()

        self.service = GTOComparisonService(database_path)
        self.site = site
        self.stakes = stakes
        self.hero_position = hero_position
        self.villain_position = villain_position
        self.location = location
        self.pot_type = pot_type
        self.board_texture = board_texture

    @Slot()
    def run(self) -> None:
        try:
            rows: list[dict[str, Any]] = []

            for stat_label, stat_key in SpotEngine.SUPPORTED_STATS.items():
                pool, numerator, denominator = (
                    self.service.calculate_population_stat(
                        stat_key=stat_key,
                        site=self.site,
                        stakes=self.stakes,
                        hero_position=self.hero_position,
                        villain_position=self.villain_position,
                        location=self.location,
                        pot_type=self.pot_type,
                        board_texture=self.board_texture,
                    )
                )

                gto = self.service.get_baseline(
                    self.site or "ALL",
                    self.stakes or "ALL",
                    self.hero_position or "ALL",
                    self.villain_position or "ALL",
                    self.location or "ALL",
                    self.pot_type or "ALL",
                    self.board_texture or "ALL",
                    stat_key,
                )

                delta = pool - gto if gto is not None else None

                if denominator == 0:
                    confidence = "Yok"
                elif denominator < 100:
                    confidence = "Çok düşük"
                elif denominator < 500:
                    confidence = "Düşük"
                elif denominator < 2500:
                    confidence = "Orta"
                else:
                    confidence = "Yüksek"

                if gto is None:
                    interpretation = "GTO referansı girilmedi"
                elif abs(delta) < 2:
                    interpretation = "Pool GTO'ya yakın"
                elif delta > 0:
                    interpretation = "Pool fazla kullanıyor"
                else:
                    interpretation = "Pool eksik kullanıyor"

                rows.append(
                    {
                        "stat": stat_label,
                        "stat_key": stat_key,
                        "pool": pool,
                        "gto": gto,
                        "delta": delta,
                        "numerator": numerator,
                        "denominator": denominator,
                        "confidence": confidence,
                        "interpretation": interpretation,
                    }
                )

            self.finished.emit(rows)

        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MDAMatrixExplorer(QWidget):
    POSITIONS = ["BTN", "CO", "HJ", "UTG", "SB", "BB"]

    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = database_path
        self.service = GTOComparisonService(database_path)

        self.worker_thread: QThread | None = None
        self.worker: MDAMatrixWorker | None = None
        self.filters_loaded = False
        self.current_rows: list[dict[str, Any]] = []

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("MDA Matrix")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Seçilen spot için Pool, GTO, Delta ve sample. "
            "GTO sütununu doğrudan düzenleyebilirsin."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filter_frame = QFrame()
        filter_frame.setObjectName("MatrixFilters")

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

        self.calculate_button = QPushButton("Tüm Statları Hesapla")
        self.save_button = QPushButton("GTO Değerlerini Kaydet")
        self.only_samples_checkbox = QCheckBox(
            "Sadece opportunity bulunan statları göster"
        )
        self.only_samples_checkbox.setChecked(True)

        self.calculate_button.clicked.connect(self.refresh_matrix)
        self.save_button.clicked.connect(self.save_gto_values)
        self.only_samples_checkbox.stateChanged.connect(
            self._apply_sample_filter
        )

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

        button_row = QHBoxLayout()
        button_row.addWidget(self.calculate_button)
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.only_samples_checkbox)
        button_row.addStretch()

        grid.addLayout(button_row, 2, 0, 1, 7)
        root.addWidget(filter_frame)

        self.spot_label = QLabel("Spot: Genel — IP + OOP — Tüm Potlar")
        self.spot_label.setObjectName("MatrixSpot")
        root.addWidget(self.spot_label)

        self.status_label = QLabel(
            "Filtreleri seçip Tüm Statları Hesapla düğmesine bas."
        )
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            [
                "Stat",
                "Pool %",
                "GTO % (düzenlenebilir)",
                "Delta",
                "Made",
                "Opportunity",
                "Güven",
                "Yorum",
            ]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        for index in range(1, 7):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        header.setSectionResizeMode(
            7,
            QHeaderView.ResizeMode.Stretch,
        )

        root.addWidget(self.table, 1)

        note = QLabel(
            "GTO hücresine yüzde değerini yaz. Örnek: 35 veya 35.5. "
            "Kaydet düğmesi aynı spot için bütün değerleri topluca saklar."
        )
        note.setObjectName("PageSubtitle")
        note.setWordWrap(True)
        root.addWidget(note)

        self.setStyleSheet(
            """
            QFrame#MatrixFilters {
                background: #171b24;
                border: 1px solid #303744;
                border-radius: 12px;
            }

            QLabel#MatrixSpot {
                padding: 14px 16px;
                background: #23262d;
                border: 1px solid #343944;
                border-radius: 10px;
                font-size: 15px;
                font-weight: 700;
            }

            QTableWidget::item {
                padding: 5px;
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
                "MDA Filtre Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def refresh_matrix(self) -> None:
        if self.worker_thread is not None:
            return

        site = str(self.site_combo.currentData() or "")
        stakes = str(self.stakes_combo.currentData() or "")
        hero = str(self.hero_combo.currentData() or "")
        villain = str(self.villain_combo.currentData() or "")
        location = str(self.location_combo.currentData() or "")
        pot_type = str(self.pot_type_combo.currentData() or "")
        board_texture = str(
            self.texture_combo.currentData() or ""
        )

        parts = [hero or "Tüm Pozisyonlar"]

        if villain:
            parts.append(f"vs {villain}")

        parts.append(location or "IP + OOP")
        parts.append(pot_type or "Tüm Potlar")
        parts.append(board_texture or "Tüm Boardlar")

        self.spot_label.setText("Spot: " + " — ".join(parts))
        self.status_label.setText("Tüm statlar hesaplanıyor…")
        self.calculate_button.setEnabled(False)
        self.save_button.setEnabled(False)

        self.worker_thread = QThread(self)
        self.worker = MDAMatrixWorker(
            database_path=self.database_path,
            site=site,
            stakes=stakes,
            hero_position=hero,
            villain_position=villain,
            location=location,
            pot_type=pot_type,
            board_texture=board_texture,
        )
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._matrix_finished)
        self.worker.failed.connect(self._matrix_failed)

        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self._cleanup_worker)

        self.worker_thread.start()

    @Slot(list)
    def _matrix_finished(self, rows: list) -> None:
        self.current_rows = rows
        self._render_rows()

        valid_samples = sum(
            1 for row in rows if row["denominator"] > 0
        )
        self.status_label.setText(
            f"{len(rows)} stat hesaplandı; "
            f"{valid_samples} statta opportunity bulundu."
        )

    def _render_rows(self) -> None:
        visible_rows = [
            row
            for row in self.current_rows
            if (
                not self.only_samples_checkbox.isChecked()
                or row["denominator"] > 0
            )
        ]

        self.table.setUpdatesEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(visible_rows))

        for row_index, row in enumerate(visible_rows):
            stat_item = QTableWidgetItem(row["stat"])
            stat_item.setFlags(
                stat_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            stat_item.setData(
                Qt.ItemDataRole.UserRole,
                row["stat_key"],
            )

            pool_item = QTableWidgetItem(f"{row['pool']:.2f}")
            pool_item.setFlags(
                pool_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            pool_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            gto_text = (
                ""
                if row["gto"] is None
                else f"{row['gto']:.2f}"
            )
            gto_item = QTableWidgetItem(gto_text)
            gto_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            gto_item.setToolTip(
                "Bu hücre düzenlenebilir. 0-100 arası değer gir."
            )

            delta_text = (
                "—"
                if row["delta"] is None
                else f"{row['delta']:+.2f}"
            )
            delta_item = QTableWidgetItem(delta_text)
            delta_item.setFlags(
                delta_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            delta_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            made_item = QTableWidgetItem(str(row["numerator"]))
            made_item.setFlags(
                made_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            made_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            opp_item = QTableWidgetItem(str(row["denominator"]))
            opp_item.setFlags(
                opp_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            opp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            confidence_item = QTableWidgetItem(row["confidence"])
            confidence_item.setFlags(
                confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable
            )

            interpretation_item = QTableWidgetItem(
                row["interpretation"]
            )
            interpretation_item.setFlags(
                interpretation_item.flags()
                & ~Qt.ItemFlag.ItemIsEditable
            )

            items = [
                stat_item,
                pool_item,
                gto_item,
                delta_item,
                made_item,
                opp_item,
                confidence_item,
                interpretation_item,
            ]

            for column_index, item in enumerate(items):
                self.table.setItem(
                    row_index,
                    column_index,
                    item,
                )

        self.table.setUpdatesEnabled(True)

    def _apply_sample_filter(self) -> None:
        if self.current_rows:
            self._render_rows()

    def save_gto_values(self) -> None:
        if not self.current_rows:
            QMessageBox.information(
                self,
                "GTO Kaydet",
                "Önce statları hesapla.",
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

        saved = 0
        invalid: list[str] = []

        for row_index in range(self.table.rowCount()):
            stat_item = self.table.item(row_index, 0)
            gto_item = self.table.item(row_index, 2)

            if stat_item is None or gto_item is None:
                continue

            stat_key = str(
                stat_item.data(Qt.ItemDataRole.UserRole)
            )
            text = gto_item.text().strip().replace(",", ".")

            if not text:
                continue

            try:
                value = float(text)
            except ValueError:
                invalid.append(stat_item.text())
                continue

            if value < 0 or value > 100:
                invalid.append(stat_item.text())
                continue

            self.service.save_baseline(
                site=site,
                stakes=stakes,
                hero_position=hero,
                villain_position=villain,
                location=location,
                pot_type=pot_type,
                board_texture=board_texture,
                stat_key=stat_key,
                gto_value=value,
                note="MDA Matrix",
            )
            saved += 1

        if invalid:
            QMessageBox.warning(
                self,
                "Bazı Değerler Kaydedilmedi",
                "0-100 aralığında olmayan veya geçersiz değerler:\n"
                + "\n".join(invalid),
            )

        if saved:
            QMessageBox.information(
                self,
                "GTO Kaydedildi",
                f"{saved} GTO referansı kaydedildi. "
                "Delta değerlerini güncellemek için tekrar hesapla.",
            )
        elif not invalid:
            QMessageBox.information(
                self,
                "GTO Kaydet",
                "Kaydedilecek GTO değeri girilmedi.",
            )

    @Slot(str)
    def _matrix_failed(self, message: str) -> None:
        QMessageBox.critical(
            self,
            "MDA Matrix Hatası",
            message,
        )
        self.status_label.setText("Hesaplama başarısız.")

    def _cleanup_worker(self) -> None:
        self.calculate_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None
