from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.player_alias_service import PlayerAliasService


class AliasManagerPage(QWidget):
    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.service = PlayerAliasService(database_path)
        self._build_ui()
        self.refresh_aliases()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Alias Manager")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Birden fazla nicki tek oyuncu veya bot grubu altında birleştir. "
            "Ham nickler silinmez."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        editor = QFrame()
        editor.setObjectName("AliasEditor")

        grid = QGridLayout(editor)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        self.alias_input = QLineEdit()
        self.alias_input.setPlaceholderText(
            "Örn: BOT_GRUP_1 veya PALOMINOT_NETWORK"
        )

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText(
            "İsteğe bağlı not"
        )

        self.players_input = QTextEdit()
        self.players_input.setPlaceholderText(
            "Her satıra bir nick yaz:\n"
            "Palominot\n"
            "Erik mager\n"
            "Auxology"
        )
        self.players_input.setMinimumHeight(105)

        self.save_button = QPushButton("Alias Grubunu Kaydet")
        self.clear_button = QPushButton("Formu Temizle")

        self.save_button.clicked.connect(self.save_alias)
        self.clear_button.clicked.connect(self.clear_form)

        grid.addWidget(QLabel("Alias / Grup Adı"), 0, 0)
        grid.addWidget(QLabel("Not"), 0, 1)
        grid.addWidget(self.alias_input, 1, 0)
        grid.addWidget(self.note_input, 1, 1)
        grid.addWidget(QLabel("Birleştirilecek Nickler"), 2, 0, 1, 2)
        grid.addWidget(self.players_input, 3, 0, 1, 2)

        buttons = QHBoxLayout()
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()

        grid.addLayout(buttons, 4, 0, 1, 2)
        root.addWidget(editor)

        search_row = QHBoxLayout()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Veritabanındaki oyuncuları ara..."
        )
        self.search_button = QPushButton("Oyuncu Ara")
        self.add_selected_button = QPushButton(
            "Seçilenleri Forma Ekle"
        )

        self.search_button.clicked.connect(self.search_players)
        self.search_input.returnPressed.connect(self.search_players)
        self.add_selected_button.clicked.connect(
            self.add_selected_players
        )

        search_row.addWidget(self.search_input)
        search_row.addWidget(self.search_button)
        search_row.addWidget(self.add_selected_button)

        root.addLayout(search_row)

        self.player_list = QListWidget()
        self.player_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.player_list.setMaximumHeight(135)
        root.addWidget(self.player_list)

        self.status_label = QLabel("")
        self.status_label.setObjectName("PageSubtitle")
        root.addWidget(self.status_label)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            [
                "Alias",
                "Nick",
                "Not",
                "Güncellendi",
            ]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)

        root.addWidget(self.table, 1)

        action_row = QHBoxLayout()

        self.remove_player_button = QPushButton(
            "Seçili Nicki Alias'tan Çıkar"
        )
        self.delete_alias_button = QPushButton(
            "Seçili Alias Grubunu Sil"
        )
        self.refresh_button = QPushButton("Yenile")

        self.remove_player_button.clicked.connect(
            self.remove_selected_player
        )
        self.delete_alias_button.clicked.connect(
            self.delete_selected_alias
        )
        self.refresh_button.clicked.connect(
            self.refresh_aliases
        )

        action_row.addWidget(self.remove_player_button)
        action_row.addWidget(self.delete_alias_button)
        action_row.addWidget(self.refresh_button)
        action_row.addStretch()

        root.addLayout(action_row)

        self.setStyleSheet(
            """
            QFrame#AliasEditor {
                background: #171b24;
                border: 1px solid #303744;
                border-radius: 12px;
            }

            QTextEdit {
                background: #11151d;
                border: 1px solid #3a4252;
                border-radius: 8px;
                padding: 8px;
                font-family: Consolas;
            }

            QListWidget {
                background: #171b24;
                border: 1px solid #303744;
                border-radius: 8px;
            }
            """
        )

    def save_alias(self) -> None:
        alias_name = self.alias_input.text().strip()

        player_names = [
            line.strip()
            for line in self.players_input
            .toPlainText()
            .replace(",", "\n")
            .splitlines()
            if line.strip()
        ]

        try:
            count = self.service.assign_players(
                alias_name=alias_name,
                player_names=player_names,
                note=self.note_input.text().strip(),
            )

            QMessageBox.information(
                self,
                "Alias Kaydedildi",
                f"{count} nick, {alias_name} altında birleştirildi.",
            )

            self.clear_form()
            self.refresh_aliases()

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Alias Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def clear_form(self) -> None:
        self.alias_input.clear()
        self.note_input.clear()
        self.players_input.clear()

    def search_players(self) -> None:
        try:
            players = self.service.search_known_players(
                self.search_input.text().strip(),
                limit=300,
            )

            self.player_list.clear()
            self.player_list.addItems(players)

            self.status_label.setText(
                f"{len(players)} oyuncu bulundu."
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Oyuncu Arama Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def add_selected_players(self) -> None:
        selected = [
            item.text()
            for item in self.player_list.selectedItems()
        ]

        if not selected:
            return

        current = {
            line.strip()
            for line in self.players_input
            .toPlainText()
            .splitlines()
            if line.strip()
        }

        current.update(selected)

        self.players_input.setPlainText(
            "\n".join(sorted(current))
        )

    def refresh_aliases(self) -> None:
        try:
            rows = self.service.list_mappings()

            self.table.setUpdatesEnabled(False)
            self.table.clearContents()
            self.table.setRowCount(len(rows))

            for row_index, row in enumerate(rows):
                values = [
                    row["alias_name"],
                    row["player_name"],
                    row["note"],
                    str(row["updated_at"]),
                ]

                for column_index, value in enumerate(values):
                    item = QTableWidgetItem(str(value))

                    if column_index == 0:
                        item.setData(
                            Qt.ItemDataRole.UserRole,
                            row["alias_name"],
                        )

                    self.table.setItem(
                        row_index,
                        column_index,
                        item,
                    )

            self.table.setUpdatesEnabled(True)

            alias_count = len(
                {
                    row["alias_name"]
                    for row in rows
                }
            )

            self.status_label.setText(
                f"{alias_count} alias grubu, "
                f"{len(rows)} nick eşleşmesi."
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Alias Liste Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def remove_selected_player(self) -> None:
        row = self.table.currentRow()

        if row < 0:
            return

        player_item = self.table.item(row, 1)

        if player_item is None:
            return

        player_name = player_item.text()

        answer = QMessageBox.question(
            self,
            "Nicki Alias'tan Çıkar",
            f"{player_name} alias eşleşmesinden çıkarılsın mı?",
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        self.service.remove_player(player_name)
        self.refresh_aliases()

    def delete_selected_alias(self) -> None:
        row = self.table.currentRow()

        if row < 0:
            return

        alias_item = self.table.item(row, 0)

        if alias_item is None:
            return

        alias_name = alias_item.text()

        answer = QMessageBox.warning(
            self,
            "Alias Grubunu Sil",
            f"{alias_name} grubundaki tüm nick eşleşmeleri silinecek.\n"
            "Ham hand verileri korunur.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        count = self.service.delete_alias(alias_name)
        self.refresh_aliases()

        QMessageBox.information(
            self,
            "Alias Silindi",
            f"{count} nick eşleşmesi kaldırıldı.",
        )
