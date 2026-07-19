from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QTreeWidget,
    QTreeWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from services.analytical_store import AnalyticalStore
from services.import_service import ImportService
from services.import_worker import ImportWorker
from ui.board_explorer import BoardExplorer
from ui.population_explorer import PopulationExplorer
from ui.gto_comparison_explorer import GTOComparisonExplorer
from ui.mda_matrix_explorer import MDAMatrixExplorer
from ui.gto_import_explorer import GTOImportExplorer
from ui.exploit_report_explorer import ExploitReportExplorer
from ui.player_explorer import PlayerExplorer
from ui.settings_page import SettingsPage
from ui.alias_manager_page import AliasManagerPage
from ui.bot_similarity_explorer import BotSimilarityExplorer
from ui.bot_group_manager import BotGroupManager
from ui.bot_profile_explorer import BotProfileExplorer
from ui.showdown_explorer import ShowdownExplorer
from ui.metric_validator_explorer import MetricValidatorExplorer
from ui.parser_debugger_explorer import ParserDebuggerExplorer
from ui.bot_dna_explorer import BotDNAExplorer
from ui.wwsf_analyzer_explorer import WWSFAnalyzerExplorer
from ui.wsd_analyzer_explorer import WSDAnalyzerExplorer
from ui.tracker_hh_export_explorer import TrackerHHExportExplorer
from ui.open_size_explorer import OpenSizeExplorer
from ui.response_explorer import ResponseExplorer
from ui.response_comparison_explorer import ResponseComparisonExplorer
from ui.size_board_strategy_explorer import SizeBoardStrategyExplorer
from ui.experiment_database_manager import ExperimentDatabaseManager
from ui.hero_adaptation_explorer import HeroAdaptationExplorer


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("PokerLab AI v1.0 Personal")
        self.resize(1600, 900)

        self.store = AnalyticalStore()
        self.import_service = ImportService()

        self.selected_files: list[str] = []
        self.import_thread: QThread | None = None
        self.import_worker: ImportWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(270)

        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(10, 12, 10, 12)
        sidebar_layout.setSpacing(10)

        sidebar_title = QLabel("PokerLab AI")
        sidebar_title.setObjectName("SidebarBrand")

        self.menu_search = QLineEdit()
        self.menu_search.setPlaceholderText("Modül ara...")
        self.menu_search.setClearButtonEnabled(True)

        self.menu = QTreeWidget()
        self.menu.setObjectName("NavigationTree")
        self.menu.setHeaderHidden(True)
        self.menu.setIndentation(14)
        self.menu.setRootIsDecorated(True)
        self.menu.setAnimated(True)
        self.menu.setUniformRowHeights(True)

        sidebar_layout.addWidget(sidebar_title)
        sidebar_layout.addWidget(self.menu_search)
        sidebar_layout.addWidget(self.menu, 1)

        self.pages = QStackedWidget()

        self.dashboard_page = self._dashboard_page()
        self.import_page = self._import_page()
        self.population_page = PopulationExplorer(
            self.store.database_path
        )
        self.player_explorer_page = PlayerExplorer(
            self.store.database_path
        )
        self.alias_manager_page = AliasManagerPage(
            self.store.database_path
        )
        self.bot_similarity_page = BotSimilarityExplorer(
            self.store.database_path
        )
        self.bot_group_page = BotGroupManager(
            self.store.database_path
        )
        self.bot_profile_page = BotProfileExplorer(
            self.store.database_path
        )
        self.bot_dna_page = BotDNAExplorer(
            self.store.database_path
        )
        self.open_size_page = OpenSizeExplorer(
            self.store.database_path
        )
        self.response_explorer_page = ResponseExplorer(
            self.store.database_path
        )
        self.response_comparison_page = ResponseComparisonExplorer(
            self.store.database_path
        )
        self.size_board_strategy_page = SizeBoardStrategyExplorer(
            self.store.database_path
        )
        self.wwsf_analyzer_page = WWSFAnalyzerExplorer(
            self.store.database_path
        )
        self.wsd_analyzer_page = WSDAnalyzerExplorer(
            self.store.database_path
        )
        self.showdown_page = ShowdownExplorer(
            self.store.database_path
        )
        self.metric_validator_page = MetricValidatorExplorer(
            self.store.database_path
        )
        self.parser_debugger_page = ParserDebuggerExplorer(
            self.store.database_path
        )
        self.tracker_hh_export_page = TrackerHHExportExplorer(
            self.store.database_path
        )
        self.board_explorer_page = BoardExplorer(
            self.store.database_path
        )
        self.mda_matrix_page = MDAMatrixExplorer(
            self.store.database_path
        )
        self.gto_import_page = GTOImportExplorer(
            self.store.database_path
        )
        self.exploit_report_page = ExploitReportExplorer(
            self.store.database_path
        )
        self.ai_coach_page = GTOComparisonExplorer(
            self.store.database_path
        )
        self.settings_page = SettingsPage(
            self.store.database_path
        )
        self.settings_page.database_cleared.connect(
            self._on_database_cleared
        )

        self.experiment_database_page = ExperimentDatabaseManager(
            self.store.database_path
        )
        self.hero_adaptation_page = HeroAdaptationExplorer(
            self.store.database_path
        )
        self.module_registry = [
            ("Core", "dashboard", "Dashboard", self.dashboard_page, self._refresh_dashboard, ("home", "özet")),
            ("Core", "import", "Import", self.import_page, None, ("hand history", "yükle")),
            ("Core", "population", "Population", self.population_page, self._refresh_callback(self.population_page, "refresh_filters"), ("pool", "havuz")),

            ("Bot Lab", "player_explorer", "Player Explorer", self.player_explorer_page, self._refresh_callback(self.player_explorer_page, "refresh_filters"), ("player", "oyuncu")),
            ("Bot Lab", "alias_manager", "Alias Manager", self.alias_manager_page, self._refresh_callback(self.alias_manager_page, "refresh_aliases"), ("alias", "grup")),
            ("Bot Lab", "bot_groups", "Bot Group Manager", self.bot_group_page, self._refresh_callback(self.bot_group_page, "refresh_filters"), ("bot", "group", "cluster", "grup")),
            ("Bot Lab", "bot_similarity", "Bot Similarity", self.bot_similarity_page, self._refresh_callback(self.bot_similarity_page, "refresh_filters"), ("bot", "benzerlik")),
            ("Bot Lab", "bot_profile", "Bot Profile Report", self.bot_profile_page, self._refresh_callback(self.bot_profile_page, "refresh_filters"), ("bot", "profil")),
            ("Bot Lab", "bot_dna", "Bot DNA Engine", self.bot_dna_page, self._refresh_callback(self.bot_dna_page, "refresh_filters"), ("dna", "fingerprint")),

            ("Open Size Lab", "open_size", "Open Size Explorer", self.open_size_page, self._refresh_callback(self.open_size_page, "refresh_filters"), ("open", "size")),
            ("Open Size Lab", "pool_response", "Pool Response Explorer", self.response_explorer_page, self._refresh_callback(self.response_explorer_page, "refresh_filters"), ("response", "fold", "3bet")),
            ("Open Size Lab", "response_compare", "Bot vs Pool Response", self.response_comparison_page, self._refresh_callback(self.response_comparison_page, "refresh_filters"), ("bot", "pool", "pressure", "comparison")),
            ("Open Size Lab", "size_board", "Size × Board Strategy", self.size_board_strategy_page, self._refresh_callback(self.size_board_strategy_page, "refresh_filters"), ("board", "texture")),

            ("Hero Lab", "experiment_database", "Experiment Database Manager", self.experiment_database_page, self._refresh_callback(self.experiment_database_page, "refresh_all"), ("experiment", "database", "5k")),
            ("Hero Lab", "hero_adaptation", "Hero Adaptation Analyzer", self.hero_adaptation_page, self._refresh_callback(self.hero_adaptation_page, "refresh_experiments"), ("hero", "adaptation", "drift")),

            ("Showdown & MDA", "wwsf_analyzer", "WWSF Analyzer", self.wwsf_analyzer_page, self._refresh_callback(self.wwsf_analyzer_page, "refresh_filters"), ("wwsf",)),
            ("Showdown & MDA", "wsd_analyzer", "W$SD Analyzer", self.wsd_analyzer_page, self._refresh_callback(self.wsd_analyzer_page, "refresh_filters"), ("wsd", "showdown")),
            ("Showdown & MDA", "showdown_report", "WWSF / W$SD Report", self.showdown_page, self._refresh_callback(self.showdown_page, "refresh_filters"), ("report", "breakdown")),
            ("Showdown & MDA", "metric_validator", "Metric Validator", self.metric_validator_page, self._refresh_callback(self.metric_validator_page, "refresh_filters"), ("validator", "doğrula")),

            ("Solver & Reports", "board_explorer", "Board Explorer", self.board_explorer_page, self._refresh_callback(self.board_explorer_page, "refresh_filters"), ("board", "flop")),
            ("Solver & Reports", "mda_matrix", "MDA Matrix", self.mda_matrix_page, self._refresh_callback(self.mda_matrix_page, "refresh_filters"), ("mda", "matrix")),
            ("Solver & Reports", "gto_import", "GTO Import", self.gto_import_page, self._refresh_callback(self.gto_import_page, "refresh_filters"), ("gto", "solver")),
            ("Solver & Reports", "exploit_report", "Exploit Report", self.exploit_report_page, self._refresh_callback(self.exploit_report_page, "refresh_filters"), ("exploit", "report")),
            ("Solver & Reports", "ai_coach", "AI Coach", self.ai_coach_page, self._refresh_callback(self.ai_coach_page, "refresh_filters"), ("coach", "öneri")),

            ("System", "parser_debugger", "Parser Debugger", self.parser_debugger_page, self._refresh_callback(self.parser_debugger_page, "refresh_filters"), ("parser", "debug")),
            ("System", "tracker_export", "Tracker HH Export", self.tracker_hh_export_page, self._refresh_callback(self.tracker_hh_export_page, "refresh_filters"), ("export", "h2n")),
            ("System", "settings", "Settings", self.settings_page, None, ("ayar", "database")),
        ]

        self.modules_by_key = {}
        self.menu_items_by_key = {}
        self.category_items = {}

        category_order = [
            "Core",
            "Bot Lab",
            "Open Size Lab",
            "Hero Lab",
            "Showdown & MDA",
            "Solver & Reports",
            "System",
        ]

        for category in category_order:
            category_item = QTreeWidgetItem([category])
            category_item.setData(0, Qt.ItemDataRole.UserRole, "")
            category_item.setFlags(
                category_item.flags()
                & ~Qt.ItemFlag.ItemIsSelectable
            )
            self.menu.addTopLevelItem(category_item)
            self.category_items[category] = category_item

            for (
                module_category,
                key,
                title,
                page,
                refresh,
                keywords,
            ) in self.module_registry:
                if module_category != category:
                    continue

                self.pages.addWidget(page)
                self.modules_by_key[key] = {
                    "title": title,
                    "page": page,
                    "refresh": refresh,
                    "category": category,
                    "keywords": keywords,
                }

                item = QTreeWidgetItem([title])
                item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    key,
                )
                category_item.addChild(item)
                self.menu_items_by_key[key] = item

            category_item.setExpanded(True)

        self.menu.itemClicked.connect(
            self._on_navigation_clicked
        )
        self.menu_search.textChanged.connect(
            self._filter_navigation
        )

        root.addWidget(self.sidebar)
        root.addWidget(self.pages, 1)

        self._apply_style()
        self.navigate_to("dashboard")

    def _refresh_callback(
        self,
        page: QWidget,
        method_name: str,
    ):
        method = getattr(page, method_name, None)

        if not callable(method):
            return None

        def callback() -> None:
            method()

        return callback

    def _on_navigation_clicked(
        self,
        item: QTreeWidgetItem,
        _column: int,
    ) -> None:
        key = str(
            item.data(
                0,
                Qt.ItemDataRole.UserRole,
            )
            or ""
        )

        if key:
            self.navigate_to(key)
        else:
            item.setExpanded(
                not item.isExpanded()
            )

    def navigate_to(self, key: str) -> None:
        module = self.modules_by_key.get(key)

        if module is None:
            QMessageBox.warning(
                self,
                "Navigation",
                f"Modül bulunamadı: {key}",
            )
            return

        self.pages.setCurrentWidget(
            module["page"]
        )

        item = self.menu_items_by_key.get(key)

        if item is not None:
            self.menu.setCurrentItem(item)

        refresh = module["refresh"]

        if refresh is not None:
            try:
                refresh()
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    f"{module['title']} Yenileme Hatası",
                    f"{type(exc).__name__}: {exc}",
                )

    def _filter_navigation(
        self,
        text: str,
    ) -> None:
        query = text.strip().lower()

        for (
            category,
            category_item,
        ) in self.category_items.items():
            visible_count = 0

            for index in range(
                category_item.childCount()
            ):
                child = category_item.child(index)
                key = str(
                    child.data(
                        0,
                        Qt.ItemDataRole.UserRole,
                    )
                    or ""
                )
                module = self.modules_by_key[key]

                haystack = " ".join(
                    [
                        module["title"],
                        module["category"],
                        *module["keywords"],
                    ]
                ).lower()

                visible = (
                    not query
                    or query in haystack
                )

                child.setHidden(
                    not visible
                )

                if visible:
                    visible_count += 1

            category_item.setHidden(
                visible_count == 0
            )

            if query and visible_count:
                category_item.setExpanded(True)

    def _dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(16)

        title = QLabel("Dashboard")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "PokerLab AI veri tabanı ve import özeti"
        )
        subtitle.setObjectName("PageSubtitle")

        self.total_hands_label = QLabel("Toplam Hand: 0")
        self.total_hands_label.setObjectName("StatLabel")

        self.total_players_label = QLabel("Toplam Oyuncu: 0")
        self.total_players_label.setObjectName("StatLabel")

        self.total_actions_label = QLabel("Toplam Aksiyon: 0")
        self.total_actions_label.setObjectName("StatLabel")

        engine_label = QLabel("Motor: DuckDB")
        engine_label.setObjectName("InfoLabel")

        version_label = QLabel("Sürüm: v0.9")
        version_label.setObjectName("InfoLabel")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addWidget(self.total_hands_label)
        layout.addWidget(self.total_players_label)
        layout.addWidget(self.total_actions_label)
        layout.addSpacing(8)
        layout.addWidget(engine_label)
        layout.addWidget(version_label)
        layout.addStretch()

        return page

    def _import_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        title = QLabel("Hand History Import")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "PokerStars, GGPoker ve CoinPoker dosyalarını içeri aktar."
        )
        subtitle.setObjectName("PageSubtitle")

        self.import_info = QLabel("Henüz klasör seçilmedi.")
        self.import_info.setWordWrap(True)
        self.import_info.setObjectName("ImportInfo")

        self.select_button = QPushButton("Klasör Seç")
        self.start_button = QPushButton("Import Başlat")
        self.export_button = QPushButton("Parquet Dışa Aktar")
        self.cancel_button = QPushButton("İptal")

        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(False)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.progress_label = QLabel("0 / 0 dosya")
        self.progress_label.setObjectName("ProgressLabel")

        self.import_speed_label = QLabel(
            "Turbo Import: hazır • 0 hand/sn • ETA --:--"
        )
        self.import_speed_label.setObjectName("ProgressLabel")

        self.select_button.clicked.connect(self.select_folder)
        self.start_button.clicked.connect(self.start_import)
        self.export_button.clicked.connect(self.export_parquet)
        self.cancel_button.clicked.connect(self.cancel_import)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addWidget(self.import_info)
        layout.addSpacing(8)
        layout.addWidget(self.select_button)
        layout.addWidget(self.start_button)
        layout.addWidget(self.export_button)
        layout.addWidget(self.cancel_button)
        layout.addSpacing(8)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.import_speed_label)
        layout.addStretch()

        return page

    def _placeholder_page(self, title_text: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 28, 28, 28)

        title = QLabel(title_text)
        title.setObjectName("PageTitle")

        subtitle = QLabel("Bu ekran sonraki sürümde aktif olacak.")
        subtitle.setObjectName("PageSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch()

        return page

    def select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Hand History Klasörü Seç",
        )

        if not folder:
            return

        self.selected_files = self.import_service.scan_folder(folder)

        self.import_info.setText(
            f"Klasör: {folder}\n"
            f"Bulunan TXT/XML dosyası: {len(self.selected_files)}"
        )
        self.start_button.setEnabled(bool(self.selected_files))
        self.progress_bar.setValue(0)
        self.progress_label.setText(
            f"0 / {len(self.selected_files)} dosya"
        )

    def start_import(self) -> None:
        if not self.selected_files:
            return

        self.select_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.cancel_button.setEnabled(True)

        self.import_thread = QThread(self)
        self.import_worker = ImportWorker(
            self.selected_files,
            self.store.database_path,
        )
        self.import_worker.moveToThread(self.import_thread)

        self.import_thread.started.connect(
            self.import_worker.run
        )
        self.import_worker.progress.connect(
            self.on_import_progress
        )
        self.import_worker.performance.connect(
            self.on_import_performance
        )
        self.import_worker.finished.connect(
            self.on_import_finished
        )
        self.import_worker.failed.connect(
            self.on_import_failed
        )

        self.import_worker.finished.connect(
            self.import_thread.quit
        )
        self.import_worker.failed.connect(
            self.import_thread.quit
        )
        self.import_thread.finished.connect(
            self._cleanup_import_thread
        )

        self.import_thread.start()

    def cancel_import(self) -> None:
        if self.import_worker:
            self.import_worker.cancel()
            self.cancel_button.setEnabled(False)

    def on_import_progress(
        self,
        current: int,
        total: int,
        file_path: str,
    ) -> None:
        percent = int((current / total) * 100) if total else 0
        self.progress_bar.setValue(percent)
        self.progress_label.setText(
            f"{current} / {total} dosya — "
            f"{Path(file_path).name}"
        )

    def on_import_performance(self, stats: object) -> None:
        if not isinstance(stats, dict):
            return

        rate = float(stats.get("hands_per_second", 0.0) or 0.0)
        eta_seconds = max(0, int(stats.get("eta_seconds", 0) or 0))
        minutes, seconds = divmod(eta_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        eta_text = (
            f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            if hours
            else f"{minutes:02d}:{seconds:02d}"
        )
        cached = int(stats.get("cached_files", 0) or 0)
        parsed = int(stats.get("parsed_hands", 0) or 0)
        self.import_speed_label.setText(
            f"Turbo Import: {rate:,.0f} hand/sn • "
            f"Parse: {parsed:,} • Cache: {cached} dosya • ETA {eta_text}"
        )

    def on_import_finished(
        self,
        inserted: int,
        skipped: int,
        unsupported: int,
    ) -> None:
        self.progress_bar.setValue(100)

        self.import_info.setText(
            "Import tamamlandı.\n"
            f"Yeni eklenen hand: {inserted}\n"
            f"Tekrar olduğu için atlanan: {skipped}\n"
            f"Tanımlanamayan dosya: {unsupported}\n"
            f"DuckDB toplam hand: {self.store.hand_count()}\n"
            "Turbo cache aktif: değişmeyen dosyalar sonraki importta atlanır."
        )

        self._refresh_dashboard()
        self.population_page.refresh_filters()
        self.board_explorer_page.refresh_filters()

    def on_import_failed(self, message: str) -> None:
        QMessageBox.critical(
            self,
            "Import Hatası",
            message,
        )
        self.import_info.setText(
            f"Import başarısız: {message}"
        )

    def export_parquet(self) -> None:
        if not hasattr(self.store, "export_parquet"):
            QMessageBox.information(
                self,
                "Parquet",
                "Parquet dışa aktarma özelliği v0.9'da aktif olacak.",
            )
            return

        try:
            output = self.store.export_parquet()
            self.import_info.setText(
                f"Parquet hazır:\n{output}\n"
                f"Toplam hand: {self.store.hand_count()}"
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Parquet Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def _cleanup_import_thread(self) -> None:
        self.select_button.setEnabled(True)
        self.start_button.setEnabled(
            bool(self.selected_files)
        )
        self.export_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

        self.import_worker = None
        self.import_thread = None

    def _refresh_dashboard(self) -> None:
        total = f"{self.store.hand_count():,}".replace(",", ".")
        players = f"{self.store.player_count():,}".replace(",", ".")
        actions = f"{self.store.action_count():,}".replace(",", ".")

        self.total_hands_label.setText(
            f"Toplam Hand: {total}"
        )
        self.total_players_label.setText(
            f"Toplam Oyuncu: {players}"
        )
        self.total_actions_label.setText(
            f"Toplam Aksiyon: {actions}"
        )


    def _on_database_cleared(self) -> None:
        self.selected_files = []

        self._refresh_dashboard()

        if hasattr(self, "import_info"):
            self.import_info.setText(
                "Veritabanı temizlendi. "
                "Yeni bir hand history klasörü seçebilirsin."
            )
            self.progress_bar.setValue(0)
            self.progress_label.setText("0 / 0 dosya")
            self.start_button.setEnabled(False)

        refresh_targets = [
            getattr(self, "population_page", None),
            getattr(self, "player_explorer_page", None),
            getattr(self, "board_explorer_page", None),
            getattr(self, "mda_matrix_page", None),
            getattr(self, "gto_import_page", None),
            getattr(self, "exploit_report_page", None),
            getattr(self, "ai_coach_page", None),
        ]

        for page in refresh_targets:
            if page is None:
                continue

            if hasattr(page, "filters_loaded"):
                page.filters_loaded = False

            if hasattr(page, "refresh_filters"):
                try:
                    page.refresh_filters()
                except Exception:
                    pass

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #17191d;
                color: #f3f4f6;
                font-size: 15px;
            }

            QWidget#Sidebar {
                background: #202329;
                border-right: 1px solid #343944;
            }

            QLabel#SidebarBrand {
                font-size: 22px;
                font-weight: 800;
                padding: 8px 10px;
            }

            QTreeWidget#NavigationTree {
                background: #202329;
                border: none;
                outline: none;
                font-size: 15px;
            }

            QTreeWidget#NavigationTree::item {
                min-height: 34px;
                padding: 5px 8px;
                border-radius: 7px;
            }

            QTreeWidget#NavigationTree::item:selected {
                background: #3b5ccc;
            }

            QTreeWidget#NavigationTree::item:hover {
                background: #2b3038;
            }

            QLabel#PageTitle {
                font-size: 30px;
                font-weight: 700;
            }

            QLabel#PageSubtitle {
                color: #9ca3af;
                font-size: 14px;
            }

            QLabel#StatLabel {
                font-size: 24px;
                font-weight: 700;
                padding: 18px;
                background: #23262d;
                border: 1px solid #343944;
                border-radius: 12px;
            }

            QLabel#InfoLabel {
                color: #aeb4bf;
                padding: 4px;
            }

            QLabel#ImportInfo {
                padding: 16px;
                background: #23262d;
                border: 1px solid #343944;
                border-radius: 10px;
            }

            QLabel#ProgressLabel {
                color: #aeb4bf;
            }

            QPushButton {
                min-height: 42px;
                background: #3154c9;
                border: none;
                border-radius: 8px;
                padding: 0 16px;
                font-weight: 600;
            }

            QPushButton:disabled {
                background: #3a3d44;
                color: #8a8f99;
            }

            QPushButton:hover:!disabled {
                background: #3d63df;
            }

            QProgressBar {
                min-height: 24px;
                border: 1px solid #3a3f49;
                border-radius: 8px;
                text-align: center;
                background: #252830;
            }

            QProgressBar::chunk {
                background: #3154c9;
                border-radius: 7px;
            }

            QTableWidget {
                background: #171b24;
                alternate-background-color: #1d222d;
                border: 1px solid #303744;
                border-radius: 10px;
                gridline-color: #2c3340;
            }

            QHeaderView::section {
                background: #232936;
                color: #f3f4f6;
                padding: 8px;
                border: none;
                border-right: 1px solid #343b49;
                font-weight: 700;
            }

            QLineEdit, QComboBox {
                background: #11151d;
                border: 1px solid #3a4252;
                border-radius: 7px;
                padding: 6px 9px;
            }
            """
        )
