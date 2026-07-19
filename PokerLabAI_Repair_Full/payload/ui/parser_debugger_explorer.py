from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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

from services.parser_debugger_service import (
    ParserDebuggerService,
)


class ParserDebugSearchWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        database_path: str,
        mode: str,
        entity_name: str,
        site: str,
        stakes: str,
        category: str,
        limit: int,
    ) -> None:
        super().__init__()

        self.service = ParserDebuggerService(
            database_path
        )

        self.args = {
            "mode": mode,
            "entity_name": entity_name,
            "site": site,
            "stakes": stakes,
            "category": category,
            "limit": limit,
        }

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(
                self.service.find_suspicious_hands(
                    **self.args
                )
            )
        except Exception as exc:
            self.failed.emit(
                f"{type(exc).__name__}: {exc}"
            )


class ParserDebuggerExplorer(QWidget):
    CATEGORIES = [
        (
            "Flop açıldı fakat Saw Flop değil",
            "FLOP_REACHED_NOT_SEEN",
        ),
        (
            "Saw Flop fakat flop aksiyonu yok",
            "SAW_FLOP_NO_ACTION",
        ),
        (
            "Pot kazandı fakat WWSF win değil",
            "WON_NOT_WWSF",
        ),
        (
            "Show yaptı fakat kazanmadı",
            "SHOW_NO_WIN",
        ),
        (
            "Oyuncu aksiyonu hiç yok",
            "NO_PLAYER_ACTION",
        ),
        (
            "Tüm eller",
            "ALL",
        ),
    ]

    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.database_path = database_path
        self.service = ParserDebuggerService(
            database_path
        )

        self.worker_thread: QThread | None = None
        self.worker: ParserDebugSearchWorker | None = None
        self.filters_loaded = False
        self.rows: list[dict[str, Any]] = []

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("Parser Debugger")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Bir elin neden WWSF, WTSD veya W$SD hesabına "
            "girdiğini ya da girmediğini açıklar."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        filters = QFrame()
        filters.setObjectName("ParserDebugFilters")

        grid = QGridLayout(filters)
        grid.setContentsMargins(14, 14, 14, 14)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Player", "PLAYER")
        self.mode_combo.addItem("Alias Group", "ALIAS")

        self.entity_combo = QComboBox()
        self.entity_combo.setMinimumWidth(220)

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")

        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.category_combo = QComboBox()

        for label, value in self.CATEGORIES:
            self.category_combo.addItem(
                label,
                value,
            )

        self.minimum_hands = QSpinBox()
        self.minimum_hands.setRange(
            1,
            100_000_000,
        )
        self.minimum_hands.setValue(500)
        self.minimum_hands.setSingleStep(500)

        self.result_limit = QSpinBox()
        self.result_limit.setRange(10, 5000)
        self.result_limit.setValue(300)
        self.result_limit.setSingleStep(100)

        labels = [
            "Mod",
            "Oyuncu / Alias",
            "Site",
            "Stakes",
            "Kategori",
            "Minimum Hand",
            "Sonuç Limiti",
        ]

        widgets = [
            self.mode_combo,
            self.entity_combo,
            self.site_combo,
            self.stakes_combo,
            self.category_combo,
            self.minimum_hands,
            self.result_limit,
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
        self.search_button = QPushButton(
            "Şüpheli Elleri Bul"
        )

        self.load_button.clicked.connect(
            self.load_entities
        )
        self.search_button.clicked.connect(
            self.run_search
        )

        buttons = QHBoxLayout()
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.search_button)
        buttons.addStretch()

        grid.addLayout(
            buttons,
            2,
            0,
            1,
            7,
        )

        root.addWidget(filters)

        self.status_label = QLabel(
            "Kategori seçip şüpheli elleri ara."
        )
        self.status_label.setObjectName(
            "PageSubtitle"
        )

        root.addWidget(self.status_label)

        splitter = QSplitter(
            Qt.Orientation.Horizontal
        )

        self.hand_table = QTableWidget()
        self.hand_table.setColumnCount(11)
        self.hand_table.setHorizontalHeaderLabels(
            [
                "Hand ID",
                "Player",
                "Pozisyon",
                "Site",
                "Stakes",
                "Tarih",
                "Flop",
                "Saw Flop",
                "Won",
                "Show",
                "Sebep",
            ]
        )
        self.hand_table.setAlternatingRowColors(True)
        self.hand_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.hand_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.hand_table.verticalHeader().setVisible(
            False
        )
        self.hand_table.itemSelectionChanged.connect(
            self.inspect_selected_hand
        )

        header = self.hand_table.horizontalHeader()
        for index in range(10):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.ResizeToContents,
            )
        header.setSectionResizeMode(
            10,
            QHeaderView.ResizeMode.Stretch,
        )

        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(
            8,
            0,
            0,
            0,
        )

        self.hand_info = QTextEdit()
        self.hand_info.setReadOnly(True)
        self.hand_info.setPlaceholderText(
            "Soldan bir hand seç."
        )

        self.action_table = QTableWidget()
        self.action_table.setColumnCount(6)
        self.action_table.setHorizontalHeaderLabels(
            [
                "Seq",
                "Street",
                "Player",
                "Action",
                "Amount",
                "To Amount",
            ]
        )
        self.action_table.setAlternatingRowColors(
            True
        )
        self.action_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.action_table.verticalHeader().setVisible(
            False
        )

        action_header = (
            self.action_table.horizontalHeader()
        )
        action_header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Stretch,
        )

        details_layout.addWidget(
            QLabel("Hand ve Sayaç Açıklaması")
        )
        details_layout.addWidget(
            self.hand_info,
            1,
        )
        details_layout.addWidget(
            QLabel("Tüm Aksiyonlar")
        )
        details_layout.addWidget(
            self.action_table,
            1,
        )

        splitter.addWidget(self.hand_table)
        splitter.addWidget(details)
        splitter.setSizes([800, 520])

        root.addWidget(
            splitter,
            1,
        )

        self.setStyleSheet(
            """
            QFrame#ParserDebugFilters {
                background:#171b24;
                border:1px solid #303744;
                border-radius:12px;
            }

            QTextEdit {
                background:#11151d;
                border:1px solid #303744;
                border-radius:8px;
                padding:8px;
                font-family:Consolas;
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
                    WHERE site IS NOT NULL
                      AND site <> ''
                    ORDER BY site
                    """
                ).fetchall()

                stakes = con.execute(
                    """
                    SELECT DISTINCT stakes
                    FROM hands
                    WHERE stakes IS NOT NULL
                      AND stakes <> ''
                    ORDER BY stakes
                    """
                ).fetchall()

            for row in sites:
                self.site_combo.addItem(
                    str(row[0]),
                    str(row[0]),
                )

            for row in stakes:
                self.stakes_combo.addItem(
                    str(row[0]),
                    str(row[0]),
                )

            self.filters_loaded = True

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Parser Debugger Filtre Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def load_entities(self) -> None:
        try:
            entities = self.service.available_entities(
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

            for name, hands in entities:
                self.entity_combo.addItem(
                    f"{name} ({hands:,} hands)",
                    name,
                )

            self.status_label.setText(
                f"{len(entities)} profil yüklendi."
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Profil Yükleme Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def run_search(self) -> None:
        if self.worker_thread is not None:
            return

        entity_name = str(
            self.entity_combo.currentData()
            or ""
        )

        if not entity_name:
            QMessageBox.information(
                self,
                "Parser Debugger",
                "Önce profil listesini yükleyip seçim yap.",
            )
            return

        self.load_button.setEnabled(False)
        self.search_button.setEnabled(False)
        self.status_label.setText(
            "Şüpheli eller aranıyor…"
        )

        self.worker_thread = QThread(self)
        self.worker = ParserDebugSearchWorker(
            database_path=self.database_path,
            mode=str(
                self.mode_combo.currentData()
            ),
            entity_name=entity_name,
            site=str(
                self.site_combo.currentData()
                or ""
            ),
            stakes=str(
                self.stakes_combo.currentData()
                or ""
            ),
            category=str(
                self.category_combo.currentData()
            ),
            limit=self.result_limit.value(),
        )

        self.worker.moveToThread(
            self.worker_thread
        )

        self.worker_thread.started.connect(
            self.worker.run
        )
        self.worker.finished.connect(
            self._search_finished
        )
        self.worker.failed.connect(
            self._search_failed
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

    @Slot(list)
    def _search_finished(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        self.rows = rows

        self.hand_table.setUpdatesEnabled(False)
        self.hand_table.clearContents()
        self.hand_table.setRowCount(
            len(rows)
        )

        for row_index, row in enumerate(rows):
            values = [
                row["hand_id"],
                row["player_name"],
                row["position"],
                row["site"],
                row["stakes"],
                row["played_at"],
                row["flop"],
                self._yes_no(row["saw_flop"]),
                self._yes_no(row["won_pot"]),
                self._yes_no(row["showed_cards"]),
                row["reason"],
            ]

            for column_index, value in enumerate(
                values
            ):
                item = QTableWidgetItem(
                    "" if value is None else str(value)
                )

                self.hand_table.setItem(
                    row_index,
                    column_index,
                    item,
                )

        self.hand_table.setUpdatesEnabled(True)

        self.status_label.setText(
            f"{len(rows)} el bulundu."
        )

        self.hand_info.clear()
        self.action_table.clearContents()
        self.action_table.setRowCount(0)

    @Slot(str)
    def _search_failed(
        self,
        message: str,
    ) -> None:
        QMessageBox.critical(
            self,
            "Parser Debugger Hatası",
            message,
        )
        self.status_label.setText(
            "Arama başarısız."
        )

    def _cleanup_worker(self) -> None:
        self.load_button.setEnabled(True)
        self.search_button.setEnabled(True)
        self.worker = None
        self.worker_thread = None

    def inspect_selected_hand(self) -> None:
        row_index = self.hand_table.currentRow()

        if row_index < 0 or row_index >= len(self.rows):
            return

        row = self.rows[row_index]

        try:
            result = self.service.inspect_hand(
                hand_id=row["hand_id"],
                player_name=row["player_name"],
            )

            self._show_hand_details(result)

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Hand İnceleme Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def _show_hand_details(
        self,
        result: dict[str, Any],
    ) -> None:
        hand = result["hand"]
        player = result["player"]

        lines = [
            f"Hand ID: {hand['hand_id']}",
            f"Site: {hand['site']}",
            f"Table: {hand['table_name']}",
            f"Stakes: {hand['stakes']}",
            f"Tarih: {hand['played_at']}",
            f"Player: {player['player_name']}",
            f"Pozisyon: {player['position']}",
            f"Seat: {player['seat_no']}",
            f"Stack: {player['starting_stack']}",
            f"Flop: {hand['flop']}",
            f"Turn: {hand['turn']}",
            f"River: {hand['river']}",
            f"Pot: {hand['pot']}",
            f"Rake: {hand['rake']}",
            f"Kaynak: {hand['source_file']}",
            "",
            "SAYAÇ KARARI",
            "-------------",
            *result["explanation"],
            "",
            "OYUNCU AKSİYONLARI",
            "------------------",
        ]

        for action in result["player_actions"]:
            lines.append(
                f"{action['sequence_no']:>3} | "
                f"{action['street']:<9} | "
                f"{action['action']:<10} | "
                f"amount={action['amount']} | "
                f"to={action['to_amount']}"
            )

        self.hand_info.setPlainText(
            "\n".join(lines)
        )

        actions = result["all_actions"]

        self.action_table.clearContents()
        self.action_table.setRowCount(
            len(actions)
        )

        for row_index, action in enumerate(actions):
            values = [
                action["sequence_no"],
                action["street"],
                action["player_name"],
                action["action"],
                action["amount"],
                action["to_amount"],
            ]

            for column_index, value in enumerate(
                values
            ):
                self.action_table.setItem(
                    row_index,
                    column_index,
                    QTableWidgetItem(
                        ""
                        if value is None
                        else str(value)
                    ),
                )

    def _yes_no(
        self,
        value: bool,
    ) -> str:
        return "EVET" if value else "HAYIR"
