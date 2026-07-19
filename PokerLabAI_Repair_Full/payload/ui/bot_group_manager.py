from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.bot_group_service import BotGroupService


class GroupEditorDialog(QDialog):
    def __init__(self, parent=None, name: str = "", description: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Bot Grubu")
        self.resize(460, 260)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("Örn. CoinPoker Bot Cluster")
        self.description_edit = QTextEdit(description)
        self.description_edit.setPlaceholderText("Kısa açıklama...")
        form.addRow("Grup adı", self.name_edit)
        form.addRow("Açıklama", self.description_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self.name_edit.text().strip(), self.description_edit.toPlainText().strip()


class BotGroupManager(QWidget):
    def __init__(self, database_path: str) -> None:
        super().__init__()
        self.service = BotGroupService(database_path)
        self.current_group_id: int | None = None
        self._build_ui()
        self.refresh_all()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("Bot Group Manager")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Farklı bot oyuncularını tek davranış kümesi altında birleştir. "
            "Alias gruplarından ayrıdır; burada farklı oyuncular ortak sample oluşturur."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("PageSubtitle")
        root.addWidget(title)
        root.addWidget(subtitle)

        toolbar = QHBoxLayout()
        self.new_button = QPushButton("+ Yeni Grup")
        self.edit_button = QPushButton("Grubu Düzenle")
        self.delete_button = QPushButton("Grubu Sil")
        self.refresh_button = QPushButton("Yenile")
        toolbar.addWidget(self.new_button)
        toolbar.addWidget(self.edit_button)
        toolbar.addWidget(self.delete_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.refresh_button)
        root.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Bot Grupları"))
        self.groups_table = QTableWidget(0, 4)
        self.groups_table.setHorizontalHeaderLabels(
            ["Grup", "Üye", "Hands", "Açıklama"]
        )
        self.groups_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.groups_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.groups_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.groups_table.verticalHeader().setVisible(False)
        self.groups_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.groups_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.groups_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.groups_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(self.groups_table)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.group_heading = QLabel("Bir grup seç")
        self.group_heading.setObjectName("SectionTitle")
        right_layout.addWidget(self.group_heading)

        member_toolbar = QHBoxLayout()
        self.player_search = QLineEdit()
        self.player_search.setPlaceholderText("Oyuncu ara...")
        self.player_search.setClearButtonEnabled(True)
        self.site_filter = QComboBox()
        self.site_filter.addItem("Tüm Siteler", "")
        self.minimum_hands = QSpinBox()
        self.minimum_hands.setRange(1, 100000000)
        self.minimum_hands.setValue(1000)
        self.minimum_hands.setSingleStep(1000)
        self.minimum_hands.setPrefix("Min ")
        self.select_all_button = QPushButton("Görünenleri Seç")
        self.add_button = QPushButton("Seçilenleri Gruba Ekle")
        self.remove_button = QPushButton("Üyeleri Çıkar")
        member_toolbar.addWidget(self.player_search, 1)
        member_toolbar.addWidget(self.site_filter)
        member_toolbar.addWidget(self.minimum_hands)
        member_toolbar.addWidget(self.select_all_button)
        member_toolbar.addWidget(self.add_button)
        member_toolbar.addWidget(self.remove_button)
        right_layout.addLayout(member_toolbar)

        tables = QSplitter(Qt.Orientation.Vertical)
        available_box = QWidget()
        available_layout = QVBoxLayout(available_box)
        available_layout.setContentsMargins(0, 0, 0, 0)
        available_layout.addWidget(QLabel("Oyuncu Havuzu"))
        self.players_table = self._player_table()
        available_layout.addWidget(self.players_table)

        member_box = QWidget()
        member_layout = QVBoxLayout(member_box)
        member_layout.setContentsMargins(0, 0, 0, 0)
        member_layout.addWidget(QLabel("Grup Üyeleri"))
        self.members_table = self._player_table()
        member_layout.addWidget(self.members_table)

        tables.addWidget(available_box)
        tables.addWidget(member_box)
        tables.setSizes([420, 300])
        right_layout.addWidget(tables)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([520, 900])
        root.addWidget(splitter, 1)

        self.all_bots_label = QLabel("")
        self.all_bots_label.setObjectName("StatusLabel")
        root.addWidget(self.all_bots_label)

        self.status = QLabel("")
        self.status.setObjectName("StatusLabel")
        root.addWidget(self.status)

        self.new_button.clicked.connect(self._create_group)
        self.edit_button.clicked.connect(self._edit_group)
        self.delete_button.clicked.connect(self._delete_group)
        self.refresh_button.clicked.connect(self.refresh_all)
        self.groups_table.itemSelectionChanged.connect(self._group_selected)
        self.add_button.clicked.connect(self._add_selected_players)
        self.remove_button.clicked.connect(self._remove_selected_members)
        self.player_search.textChanged.connect(self._schedule_player_search)
        self.site_filter.currentIndexChanged.connect(self._schedule_player_search)
        self.minimum_hands.valueChanged.connect(self._schedule_player_search)
        self.select_all_button.clicked.connect(self.players_table.selectAll)

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self.refresh_players)

    def _player_table(self) -> QTableWidget:
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Oyuncu", "Hands"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        return table

    def refresh_all(self) -> None:
        current_site = self.site_filter.currentData() if hasattr(self, "site_filter") else ""
        self.site_filter.blockSignals(True)
        self.site_filter.clear()
        self.site_filter.addItem("Tüm Siteler", "")
        for site in self.service.list_sites():
            self.site_filter.addItem(site, site)
        index = self.site_filter.findData(current_site)
        self.site_filter.setCurrentIndex(max(0, index))
        self.site_filter.blockSignals(False)
        members, hands = self.service.all_bots_summary()
        self.all_bots_label.setText(
            f"All Bots ailesi: {members:,} benzersiz oyuncu · {hands:,} el · bütün bot grupları otomatik birleşir."
        )
        self.refresh_groups()
        self.refresh_players()
        self.refresh_members()

    def refresh_filters(self) -> None:
        self.refresh_all()

    def refresh_groups(self) -> None:
        groups = self.service.list_groups()
        selected = self.current_group_id
        self.groups_table.setRowCount(len(groups))
        select_row = -1
        for row, group in enumerate(groups):
            item = QTableWidgetItem(group.name)
            item.setData(Qt.ItemDataRole.UserRole, group.group_id)
            self.groups_table.setItem(row, 0, item)
            self.groups_table.setItem(row, 1, QTableWidgetItem(str(group.member_count)))
            self.groups_table.setItem(row, 2, QTableWidgetItem(f"{group.hand_count:,}"))
            self.groups_table.setItem(row, 3, QTableWidgetItem(group.description))
            if group.group_id == selected:
                select_row = row
        if select_row >= 0:
            self.groups_table.selectRow(select_row)
        elif groups:
            self.groups_table.selectRow(0)
        else:
            self.current_group_id = None
            self.group_heading.setText("Bir grup oluştur")

    def refresh_players(self) -> None:
        players = self.service.search_players(
            self.player_search.text(),
            5000,
            site=str(self.site_filter.currentData() or ""),
            minimum_hands=self.minimum_hands.value(),
            exclude_group_id=self.current_group_id,
        )
        self._fill_player_table(self.players_table, players)

    def refresh_members(self) -> None:
        if self.current_group_id is None:
            self.members_table.setRowCount(0)
            return
        self._fill_player_table(
            self.members_table,
            self.service.list_members(self.current_group_id),
        )

    def _fill_player_table(self, table: QTableWidget, rows: list[tuple[str, int]]) -> None:
        table.setRowCount(len(rows))
        for row, (name, hands) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(f"{hands:,}"))

    def _group_selected(self) -> None:
        selected = self.groups_table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        item = self.groups_table.item(row, 0)
        self.current_group_id = int(item.data(Qt.ItemDataRole.UserRole))
        self.group_heading.setText(f"Grup: {item.text()}")
        self.refresh_members()

    def _create_group(self) -> None:
        dialog = GroupEditorDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name, description = dialog.values()
        try:
            self.current_group_id = self.service.create_group(name, description)
            self.status.setText(f"'{name}' oluşturuldu.")
            self.refresh_groups()
        except Exception as exc:
            QMessageBox.critical(self, "Grup oluşturulamadı", str(exc))

    def _edit_group(self) -> None:
        if self.current_group_id is None:
            QMessageBox.information(self, "Bot Group", "Önce bir grup seç.")
            return
        row = self.groups_table.currentRow()
        name = self.groups_table.item(row, 0).text()
        description = self.groups_table.item(row, 3).text()
        dialog = GroupEditorDialog(self, name, description)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_name, new_description = dialog.values()
        try:
            self.service.rename_group(self.current_group_id, new_name, new_description)
            self.status.setText("Grup güncellendi.")
            self.refresh_groups()
        except Exception as exc:
            QMessageBox.critical(self, "Grup güncellenemedi", str(exc))

    def _delete_group(self) -> None:
        if self.current_group_id is None:
            return
        row = self.groups_table.currentRow()
        name = self.groups_table.item(row, 0).text()
        answer = QMessageBox.question(
            self,
            "Grubu sil",
            f"'{name}' grubu ve üyelikleri silinsin mi?\nHand verileri silinmez.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.service.delete_group(self.current_group_id)
        self.current_group_id = None
        self.status.setText("Grup silindi. Hand verileri korunuyor.")
        self.refresh_all()

    def _selected_names(self, table: QTableWidget) -> list[str]:
        rows = sorted({index.row() for index in table.selectionModel().selectedRows()})
        return [table.item(row, 0).text() for row in rows if table.item(row, 0)]

    def _add_selected_players(self) -> None:
        if self.current_group_id is None:
            QMessageBox.information(self, "Bot Group", "Önce bir grup seç veya oluştur.")
            return
        names = self._selected_names(self.players_table)
        added = self.service.add_members(self.current_group_id, names)
        self.status.setText(f"{added} oyuncu gruba eklendi.")
        self.refresh_groups()
        self.refresh_members()
        self.refresh_players()

    def _remove_selected_members(self) -> None:
        if self.current_group_id is None:
            return
        names = self._selected_names(self.members_table)
        removed = self.service.remove_members(self.current_group_id, names)
        self.status.setText(f"{removed} oyuncu gruptan çıkarıldı.")
        self.refresh_groups()
        self.refresh_members()

    def _schedule_player_search(self) -> None:
        self.search_timer.start()
