from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.tracker_hh_export_service import (
    TrackerHHExportService,
)


class HHExportWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        database_path: str,
        output_folder: str,
        mode: str,
        entity_name: str,
        site: str,
        stakes: str,
        hands_per_file: int,
    ) -> None:
        super().__init__()

        self.service = TrackerHHExportService(
            database_path
        )
        self.args = {
            "output_folder": output_folder,
            "mode": mode,
            "entity_name": entity_name,
            "site": site,
            "stakes": stakes,
            "hands_per_file": hands_per_file,
        }

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.export(
                **self.args,
                progress_callback=self._progress,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )

    def _progress(
        self,
        current: int,
        total: int,
        filename: str,
    ) -> None:
        self.progress.emit(
            current,
            total,
            filename,
        )


class TrackerHHExportExplorer(QWidget):
    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = database_path
        self.service = TrackerHHExportService(
            database_path
        )
        self.worker_thread: QThread | None = None
        self.worker: HHExportWorker | None = None

        self._build_ui()
        QTimer.singleShot(
            100,
            self.refresh_filters,
        )

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(13)

        title = QLabel("Tracker HH Export")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Seçilen ellerin orijinal hand-history metnini "
            "tracker importu için .txt dosyalarına çıkarır."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName("HHExportFilters")

        grid = QGridLayout(filters)
        grid.setContentsMargins(15, 15, 15, 15)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Tüm Eller", "ALL")
        self.mode_combo.addItem("Player", "PLAYER")
        self.mode_combo.addItem("Alias Group", "ALIAS")
        self.mode_combo.currentIndexChanged.connect(
            self._mode_changed
        )

        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumWidth(240)
        self.entity_combo.setEnabled(False)

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")

        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.minimum_hands = QSpinBox()
        self.minimum_hands.setRange(
            1,
            100_000_000,
        )
        self.minimum_hands.setValue(500)
        self.minimum_hands.setSingleStep(500)

        self.hands_per_file = QSpinBox()
        self.hands_per_file.setRange(
            100,
            500_000,
        )
        self.hands_per_file.setValue(50_000)
        self.hands_per_file.setSingleStep(10_000)

        labels = [
            "Export Modu",
            "Oyuncu / Alias",
            "Site",
            "Stakes",
            "Minimum Hand",
            "Dosya Başına Hand",
        ]
        widgets = [
            self.mode_combo,
            self.entity_combo,
            self.site_combo,
            self.stakes_combo,
            self.minimum_hands,
            self.hands_per_file,
        ]

        for index, (label, widget) in enumerate(
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

        self.load_button = QPushButton(
            "Profil Listesini Yükle"
        )
        self.load_button.setEnabled(False)
        self.load_button.clicked.connect(
            self.load_entities
        )

        grid.addWidget(
            self.load_button,
            2,
            0,
            1,
            2,
        )

        root.addWidget(filters)

        folder_frame = QFrame()
        folder_frame.setObjectName("HHExportFilters")
        folder_layout = QHBoxLayout(folder_frame)
        folder_layout.setContentsMargins(
            15,
            15,
            15,
            15,
        )

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText(
            "Export klasörü seç..."
        )

        self.folder_button = QPushButton(
            "Klasör Seç"
        )
        self.folder_button.clicked.connect(
            self.choose_folder
        )

        self.export_button = QPushButton(
            "HH Export Başlat"
        )
        self.export_button.clicked.connect(
            self.start_export
        )

        folder_layout.addWidget(
            QLabel("Çıktı Klasörü")
        )
        folder_layout.addWidget(
            self.output_edit,
            1,
        )
        folder_layout.addWidget(
            self.folder_button,
        )
        folder_layout.addWidget(
            self.export_button,
        )

        root.addWidget(folder_frame)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.status_label = QLabel(
            "Export için klasör seç."
        )
        self.status_label.setObjectName("PageSubtitle")

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText(
            "Export sonucu burada görünecek."
        )

        root.addWidget(self.progress_bar)
        root.addWidget(self.status_label)
        root.addWidget(self.result_text, 1)

        self.warning_label = QLabel(
            "Çıktı, kaynak dosyadaki orijinal HH sözdizimini korur. "
            "CSV/JSON üretmez."
        )
        self.warning_label.setObjectName("PageSubtitle")
        self.warning_label.setWordWrap(True)

        root.addWidget(self.warning_label)

        self.setStyleSheet(
            """
            QFrame#HHExportFilters {
                background:#171b24;
                border:1px solid #303744;
                border-radius:12px;
            }

            QTextEdit {
                background:#11151d;
                border:1px solid #303744;
                border-radius:8px;
                padding:10px;
            }
            """
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(
            100,
            self.refresh_filters,
        )

    def _mode_changed(self) -> None:
        mode = str(
            self.mode_combo.currentData()
        )
        enabled = mode in {
            "PLAYER",
            "ALIAS",
        }

        self.entity_combo.setEnabled(enabled)
        self.load_button.setEnabled(enabled)

        if not enabled:
            self.entity_combo.clear()

    def refresh_filters(self) -> None:
        try:
            current_site = self.site_combo.currentData()
            current_stakes = (
                self.stakes_combo.currentData()
            )

            with self.service.connect() as con:
                sites = con.execute(
                    """
                    SELECT DISTINCT TRIM(site)
                    FROM hands
                    WHERE site IS NOT NULL
                      AND TRIM(site) <> ''
                    ORDER BY 1
                    """
                ).fetchall()

                stakes = con.execute(
                    """
                    SELECT DISTINCT TRIM(stakes)
                    FROM hands
                    WHERE stakes IS NOT NULL
                      AND TRIM(stakes) <> ''
                    ORDER BY 1
                    """
                ).fetchall()

            self.site_combo.clear()
            self.site_combo.addItem(
                "Tüm Siteler",
                "",
            )

            for row in sites:
                value = str(row[0]).strip()

                if value:
                    self.site_combo.addItem(
                        value,
                        value,
                    )

            self.stakes_combo.clear()
            self.stakes_combo.addItem(
                "Tüm Limitler",
                "",
            )

            for row in stakes:
                value = str(row[0]).strip()

                if value:
                    self.stakes_combo.addItem(
                        value,
                        value,
                    )

            site_index = self.site_combo.findData(
                current_site
            )

            if site_index >= 0:
                self.site_combo.setCurrentIndex(
                    site_index
                )

            stakes_index = (
                self.stakes_combo.findData(
                    current_stakes
                )
            )

            if stakes_index >= 0:
                self.stakes_combo.setCurrentIndex(
                    stakes_index
                )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "HH Export Filtre Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def load_entities(self) -> None:
        try:
            rows = self.service.available_entities(
                mode=str(
                    self.mode_combo.currentData()
                ),
                site=str(
                    self.site_combo.currentData()
                    or ""
                ),
                stakes=str(
                    self.stakes_combo.currentData()
                    or ""
                ),
                minimum_hands=(
                    self.minimum_hands.value()
                ),
            )

            self.entity_combo.clear()

            for name, hands in rows:
                self.entity_combo.addItem(
                    f"{name} ({hands:,} hands)",
                    name,
                )

            self.status_label.setText(
                f"{len(rows)} profil yüklendi."
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "HH Export Profil Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "HH Export Klasörü Seç",
        )

        if folder:
            self.output_edit.setText(folder)

    def start_export(self) -> None:
        if self.worker_thread is not None:
            return

        output_folder = self.output_edit.text().strip()

        if not output_folder:
            QMessageBox.information(
                self,
                "Tracker HH Export",
                "Önce çıktı klasörü seç.",
            )
            return

        mode = str(
            self.mode_combo.currentData()
        )
        entity_name = str(
            self.entity_combo.currentData()
            or ""
        )

        if mode in {"PLAYER", "ALIAS"} and not entity_name:
            QMessageBox.information(
                self,
                "Tracker HH Export",
                "Önce oyuncu veya alias seç.",
            )
            return

        self.export_button.setEnabled(False)
        self.folder_button.setEnabled(False)
        self.load_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.result_text.clear()
        self.status_label.setText(
            "Kaynak hand dosyaları taranıyor…"
        )

        self.worker_thread = QThread(self)
        self.worker = HHExportWorker(
            database_path=self.database_path,
            output_folder=output_folder,
            mode=mode,
            entity_name=entity_name,
            site=str(
                self.site_combo.currentData()
                or ""
            ),
            stakes=str(
                self.stakes_combo.currentData()
                or ""
            ),
            hands_per_file=(
                self.hands_per_file.value()
            ),
        )

        self.worker.moveToThread(
            self.worker_thread
        )

        self.worker_thread.started.connect(
            self.worker.run
        )
        self.worker.progress.connect(
            self._progress_changed
        )
        self.worker.finished.connect(
            self._export_finished
        )
        self.worker.failed.connect(
            self._export_failed
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

    @Slot(int, int, str)
    def _progress_changed(
        self,
        current: int,
        total: int,
        filename: str,
    ) -> None:
        percent = (
            int(current / total * 100)
            if total
            else 0
        )

        self.progress_bar.setValue(percent)
        self.status_label.setText(
            f"{current}/{total} kaynak dosya — {filename}"
        )

    @Slot(dict)
    def _export_finished(
        self,
        result: dict[str, Any],
    ) -> None:
        self.progress_bar.setValue(100)

        lines = [
            "TRACKER HH EXPORT TAMAMLANDI",
            "=" * 60,
            (
                f"Seçilen hand: "
                f"{result['selected_hands']:,}"
            ),
            (
                f"Export edilen: "
                f"{result['exported_hands']:,}"
            ),
            (
                f"Eksik hand ID: "
                f"{result['missing_hand_ids']:,}"
            ),
            (
                f"Eksik kaynak dosya: "
                f"{result['missing_source_files']:,}"
            ),
            (
                f"Oluşturulan .txt: "
                f"{len(result['exported_files'])}"
            ),
            "",
            f"Çıktı: {result['output_folder']}",
            f"Rapor: {result['report_file']}",
        ]

        self.result_text.setPlainText(
            "\n".join(lines)
        )
        self.status_label.setText(
            "HH export tamamlandı."
        )

    @Slot(str)
    def _export_failed(
        self,
        message: str,
    ) -> None:
        QMessageBox.critical(
            self,
            "Tracker HH Export Hatası",
            message,
        )
        self.status_label.setText(
            "HH export başarısız."
        )

    def _cleanup_worker(self) -> None:
        self.export_button.setEnabled(True)
        self.folder_button.setEnabled(True)

        mode = str(
            self.mode_combo.currentData()
        )
        self.load_button.setEnabled(
            mode in {"PLAYER", "ALIAS"}
        )

        self.worker = None
        self.worker_thread = None
