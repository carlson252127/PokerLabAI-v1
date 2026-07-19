from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.database_admin_service import DatabaseAdminService


class SettingsPage(QWidget):
    database_cleared = Signal()

    CONFIRMATION_TEXT = "SIL"

    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.admin_service = DatabaseAdminService(
            database_path
        )

        self._build_ui()
        self.refresh_counts()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(16)

        title = QLabel("Settings")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Veritabanı yönetimi ve güvenli sıfırlama."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        status_card = QFrame()
        status_card.setObjectName("SettingsCard")

        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(18, 18, 18, 18)
        status_layout.setSpacing(8)

        status_title = QLabel("Veritabanı Durumu")
        status_title.setObjectName("SettingsCardTitle")

        self.hands_label = QLabel("Hands: 0")
        self.players_label = QLabel("Players: 0")
        self.actions_label = QLabel("Actions: 0")
        self.gto_label = QLabel("GTO Baselines: 0")

        refresh_button = QPushButton("Sayıları Yenile")
        refresh_button.clicked.connect(
            self.refresh_counts
        )

        status_layout.addWidget(status_title)
        status_layout.addWidget(self.hands_label)
        status_layout.addWidget(self.players_label)
        status_layout.addWidget(self.actions_label)
        status_layout.addWidget(self.gto_label)
        status_layout.addWidget(refresh_button)

        root.addWidget(status_card)

        danger_card = QFrame()
        danger_card.setObjectName("DangerCard")

        danger_layout = QVBoxLayout(danger_card)
        danger_layout.setContentsMargins(18, 18, 18, 18)
        danger_layout.setSpacing(10)

        danger_title = QLabel("Tehlikeli Bölge")
        danger_title.setObjectName("DangerTitle")

        description = QLabel(
            "Bu işlem tüm hand, oyuncu ve aksiyon "
            "kayıtlarını kalıcı olarak siler.\n"
            "GTO referansları korunur."
        )
        description.setWordWrap(True)

        confirmation_help = QLabel(
            'Silme düğmesini açmak için aşağıya "SIL" yaz.'
        )

        self.confirmation_input = QLineEdit()
        self.confirmation_input.setPlaceholderText("SIL")
        self.confirmation_input.textChanged.connect(
            self._update_reset_button
        )

        self.reset_button = QPushButton(
            "Tüm Hand Verisini Sil"
        )
        self.reset_button.setObjectName("DangerButton")
        self.reset_button.setEnabled(False)
        self.reset_button.clicked.connect(
            self._confirm_and_clear
        )

        danger_layout.addWidget(danger_title)
        danger_layout.addWidget(description)
        danger_layout.addWidget(confirmation_help)
        danger_layout.addWidget(self.confirmation_input)
        danger_layout.addWidget(self.reset_button)

        root.addWidget(danger_card)
        root.addStretch()

        self.setStyleSheet(
            """
            QFrame#SettingsCard {
                background: #1d222d;
                border: 1px solid #343b49;
                border-radius: 12px;
            }

            QFrame#DangerCard {
                background: #251b1d;
                border: 1px solid #7f3038;
                border-radius: 12px;
            }

            QLabel#SettingsCardTitle {
                font-size: 18px;
                font-weight: 700;
            }

            QLabel#DangerTitle {
                color: #ff8c94;
                font-size: 19px;
                font-weight: 800;
            }

            QPushButton#DangerButton {
                background: #a62f3a;
            }

            QPushButton#DangerButton:hover:!disabled {
                background: #c33a46;
            }

            QPushButton#DangerButton:disabled {
                background: #4a3033;
                color: #967b7e;
            }
            """
        )

    def refresh_counts(self) -> None:
        try:
            counts = self.admin_service.get_counts()

            self.hands_label.setText(
                "Hands: "
                + self._format_number(counts["hands"])
            )
            self.players_label.setText(
                "Players: "
                + self._format_number(counts["players"])
            )
            self.actions_label.setText(
                "Actions: "
                + self._format_number(counts["actions"])
            )
            self.gto_label.setText(
                "GTO Baselines: "
                + self._format_number(
                    counts["gto_baselines"]
                )
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Veritabanı Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def _update_reset_button(self) -> None:
        is_valid = (
            self.confirmation_input.text()
            .strip()
            .upper()
            == self.CONFIRMATION_TEXT
        )
        self.reset_button.setEnabled(is_valid)

    def _confirm_and_clear(self) -> None:
        answer = QMessageBox.warning(
            self,
            "Tüm Hand Verisini Sil",
            "Hands, players ve actions tablolarındaki "
            "bütün veriler kalıcı olarak silinecek.\n\n"
            "GTO referansları korunacak.\n\n"
            "Devam edilsin mi?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.reset_button.setEnabled(False)

        try:
            result = self.admin_service.clear_hand_data()
            self.admin_service.checkpoint()

            self.confirmation_input.clear()
            self.refresh_counts()
            self.database_cleared.emit()

            QMessageBox.information(
                self,
                "Veritabanı Temizlendi",
                "Silinen kayıtlar:\n"
                f"Hands: {self._format_number(result['deleted_hands'])}\n"
                f"Players: {self._format_number(result['deleted_players'])}\n"
                f"Actions: {self._format_number(result['deleted_actions'])}\n\n"
                "Korunan GTO referansı: "
                f"{self._format_number(result['preserved_gto'])}",
            )

        except Exception as exc:
            self._update_reset_button()

            QMessageBox.critical(
                self,
                "Silme Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def _format_number(self, value: int) -> str:
        return f"{int(value):,}".replace(",", ".")
