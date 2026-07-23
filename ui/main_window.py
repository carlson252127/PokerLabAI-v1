from __future__ import annotations

from importlib import import_module
from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
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

        self.module_registry = [
            ("Core", "dashboard", "Dashboard", self._local_page_factory("dashboard_page", self._dashboard_page), None, ("home", "özet")),
            ("Core", "import", "Import", self._local_page_factory("import_page", self._import_page), None, ("hand history", "yükle")),
            ("Core", "population", "Population", self._database_page_factory("population_page", "ui.population_explorer", "PopulationExplorer"), "refresh_filters", ("pool", "havuz")),

            ("Bot Lab", "player_explorer", "Player Explorer", self._database_page_factory("player_explorer_page", "ui.player_explorer", "PlayerExplorer"), "refresh_filters", ("player", "oyuncu")),
            ("Bot Lab", "alias_manager", "Alias Manager", self._database_page_factory("alias_manager_page", "ui.alias_manager_page", "AliasManagerPage"), "refresh_aliases", ("alias", "grup")),
            ("Bot Lab", "bot_groups", "Bot Group Manager", self._database_page_factory("bot_group_page", "ui.bot_group_manager", "BotGroupManager"), "refresh_filters", ("bot", "group", "cluster", "grup")),
            ("Bot Lab", "bot_similarity", "Bot Similarity", self._database_page_factory("bot_similarity_page", "ui.bot_similarity_explorer", "BotSimilarityExplorer"), "refresh_filters", ("bot", "benzerlik")),
            ("Bot Lab", "bot_profile", "Bot Profile Report", self._database_page_factory("bot_profile_page", "ui.bot_profile_explorer", "BotProfileExplorer"), "refresh_filters", ("bot", "profil")),
            ("Bot Lab", "bot_dna", "Bot DNA Engine", self._database_page_factory("bot_dna_page", "ui.bot_dna_explorer", "BotDNAExplorer"), "refresh_filters", ("dna", "fingerprint")),

            ("Open Size Lab", "open_size", "Open Size Explorer", self._database_page_factory("open_size_page", "ui.open_size_explorer", "OpenSizeExplorer"), "refresh_filters", ("open", "size")),
            ("Open Size Lab", "pool_response", "Pool Response Explorer", self._database_page_factory("response_explorer_page", "ui.response_explorer", "ResponseExplorer"), "refresh_filters", ("response", "fold", "3bet")),
            ("Open Size Lab", "response_compare", "Bot vs Pool Response", self._database_page_factory("response_comparison_page", "ui.response_comparison_explorer", "ResponseComparisonExplorer"), "refresh_filters", ("bot", "pool", "pressure", "comparison")),
            ("Open Size Lab", "board_matchup", "Board Matchup & Pool Response", self._database_page_factory("board_matchup_page", "ui.board_matchup_explorer", "BoardMatchupExplorer"), "refresh_filters", ("board", "matchup", "human", "pool", "cbet", "fold", "overbet")),
            ("Open Size Lab", "size_board", "Size × Board Strategy", self._database_page_factory("size_board_strategy_page", "ui.size_board_strategy_explorer", "SizeBoardStrategyExplorer"), "refresh_filters", ("board", "texture")),

            ("Hero Lab", "experiment_database", "Experiment Database Manager", self._database_page_factory("experiment_database_page", "ui.experiment_database_manager", "ExperimentDatabaseManager"), "refresh_all", ("experiment", "database", "5k")),
            ("Hero Lab", "hero_adaptation", "Hero Adaptation Analyzer", self._database_page_factory("hero_adaptation_page", "ui.hero_adaptation_explorer", "HeroAdaptationExplorer"), "refresh_experiments", ("hero", "adaptation", "drift")),

            ("Showdown & MDA", "wwsf_analyzer", "WWSF Analyzer", self._database_page_factory("wwsf_analyzer_page", "ui.wwsf_analyzer_explorer", "WWSFAnalyzerExplorer"), "refresh_filters", ("wwsf",)),
            ("Showdown & MDA", "wsd_analyzer", "W$SD Analyzer", self._database_page_factory("wsd_analyzer_page", "ui.wsd_analyzer_explorer", "WSDAnalyzerExplorer"), "refresh_filters", ("wsd", "showdown")),
            ("Showdown & MDA", "showdown_report", "WWSF / W$SD Report", self._database_page_factory("showdown_page", "ui.showdown_explorer", "ShowdownExplorer"), "refresh_filters", ("report", "breakdown")),
            ("Showdown & MDA", "metric_validator", "Metric Validator", self._database_page_factory("metric_validator_page", "ui.metric_validator_explorer", "MetricValidatorExplorer"), "refresh_filters", ("validator", "doğrula")),

            ("Solver & Reports", "board_explorer", "Board Explorer", self._database_page_factory("board_explorer_page", "ui.board_explorer", "BoardExplorer"), "refresh_filters", ("board", "flop")),
            ("Solver & Reports", "mda_matrix", "MDA Matrix", self._database_page_factory("mda_matrix_page", "ui.mda_matrix_explorer", "MDAMatrixExplorer"), "refresh_filters", ("mda", "matrix")),
            ("Solver & Reports", "gto_import", "GTO Import", self._database_page_factory("gto_import_page", "ui.gto_import_explorer", "GTOImportExplorer"), "refresh_filters", ("gto", "solver")),
            ("Solver & Reports", "exploit_report", "Exploit Report", self._database_page_factory("exploit_report_page", "ui.exploit_report_explorer", "ExploitReportExplorer"), "refresh_filters", ("exploit", "report")),
            ("Solver & Reports", "ai_coach", "AI Coach", self._database_page_factory("ai_coach_page", "ui.gto_comparison_explorer", "GTOComparisonExplorer"), "refresh_filters", ("coach", "öneri")),

            ("System", "parser_debugger", "Parser Debugger", self._database_page_factory("parser_debugger_page", "ui.parser_debugger_explorer", "ParserDebuggerExplorer"), "refresh_filters", ("parser", "debug")),
            ("System", "tracker_export", "Tracker HH Export", self._database_page_factory("tracker_hh_export_page", "ui.tracker_hh_export_explorer", "TrackerHHExportExplorer"), "refresh_filters", ("export", "h2n")),
            ("System", "settings", "Settings", self._database_page_factory("settings_page", "ui.settings_page", "SettingsPage"), None, ("ayar", "database")),
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
                factory,
                refresh_method,
                keywords,
            ) in self.module_registry:
                if module_category != category:
                    continue

                self.modules_by_key[key] = {
                    "title": title,
                    "page": None,
                    "factory": factory,
                    "refresh_method": refresh_method,
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

    def _local_page_factory(
        self,
        attribute_name: str,
        builder,
    ):
        def factory() -> QWidget:
            page = builder()
            setattr(self, attribute_name, page)
            return page

        return factory

    def _database_page_factory(
        self,
        attribute_name: str,
        module_name: str,
        class_name: str,
    ):
        def factory() -> QWidget:
            page_module = import_module(module_name)
            page_class = getattr(page_module, class_name)
            page = page_class(self.store.database_path)
            setattr(self, attribute_name, page)

            if attribute_name == "settings_page":
                page.database_cleared.connect(
                    self._on_database_cleared
                )

            return page

        return factory

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

        page = module["page"]

        if page is None:
            try:
                page = module["factory"]()
                self.pages.addWidget(page)
                module["page"] = page
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    f"{module['title']} Açılış Hatası",
                    f"{type(exc).__name__}: {exc}",
                )
                return

        self.pages.setCurrentWidget(page)

        item = self.menu_items_by_key.get(key)

        if item is not None:
            self.menu.setCurrentItem(item)

        refresh_method = module["refresh_method"]

        if key == "dashboard":
            try:
                self._refresh_dashboard()
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    f"{module['title']} Yenileme Hatası",
                    f"{type(exc).__name__}: {exc}",
                )
        elif refresh_method:
            refresh = getattr(page, refresh_method, None)
            if callable(refresh):
                try:
                    refresh()
                except Exception as exc:
                    QMessageBox.warning(
                        self,
                        f"{module['title']} Yenileme Hatası",
                        f"{type(exc).__name__}: {exc}",
                    )

    def _refresh_loaded_module(self, key: str) -> None:
        module = self.modules_by_key.get(key)
        if not module or module["page"] is None:
            return

        refresh_method = module["refresh_method"]
        if not refresh_method:
            return

        refresh = getattr(module["page"], refresh_method, None)
        if callable(refresh):
            refresh()

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
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("PokerLab AI Dashboard")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Veriyi içeri aktar, adayları tara ve stratejiyi doğrula."
        )
        subtitle.setObjectName("PageSubtitle")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        stats_grid = QGridLayout()
        stats_grid.setHorizontalSpacing(12)
        stats_grid.setVerticalSpacing(12)

        self.total_hands_label = QLabel("Toplam Hand\n0")
        self.total_hands_label.setObjectName("StatLabel")

        self.total_players_label = QLabel("Toplam Oyuncu\n0")
        self.total_players_label.setObjectName("StatLabel")

        self.total_actions_label = QLabel("Toplam Aksiyon\n0")
        self.total_actions_label.setObjectName("StatLabel")

        stats_grid.addWidget(self.total_hands_label, 0, 0)
        stats_grid.addWidget(self.total_players_label, 0, 1)
        stats_grid.addWidget(self.total_actions_label, 0, 2)
        stats_grid.setColumnStretch(0, 1)
        stats_grid.setColumnStretch(1, 1)
        stats_grid.setColumnStretch(2, 1)
        layout.addLayout(stats_grid)

        workflow_hero = QFrame()
        workflow_hero.setObjectName("WorkflowHero")
        hero_layout = QHBoxLayout(workflow_hero)
        hero_layout.setContentsMargins(18, 14, 18, 14)
        hero_layout.setSpacing(18)

        hero_copy = QVBoxLayout()
        hero_copy.setSpacing(3)

        eyebrow = QLabel("ÖNERİLEN ÇALIŞMA AKIŞI")
        eyebrow.setObjectName("WorkflowEyebrow")

        hero_title = QLabel("Yeni Analiz Başlat")
        hero_title.setObjectName("WorkflowTitle")

        self.dashboard_guidance_label = QLabel(
            "Veri hazırsa filtreli bot adaylarını tarayarak başla."
        )
        self.dashboard_guidance_label.setObjectName("WorkflowDescription")
        self.dashboard_guidance_label.setWordWrap(True)

        hero_copy.addWidget(eyebrow)
        hero_copy.addWidget(hero_title)
        hero_copy.addWidget(self.dashboard_guidance_label)

        self.dashboard_primary_button = QPushButton(
            "Bot Adayı Taramasını Başlat"
        )
        self.dashboard_primary_button.setObjectName("WorkflowPrimaryButton")
        self.dashboard_primary_button.setMinimumWidth(250)
        self.dashboard_primary_button.clicked.connect(
            self._start_recommended_analysis
        )

        hero_layout.addLayout(hero_copy, 1)
        hero_layout.addWidget(self.dashboard_primary_button)
        layout.addWidget(workflow_hero)

        flow_title = QLabel("Bot araştırması — 5 adım")
        flow_title.setObjectName("DashboardSectionTitle")
        layout.addWidget(flow_title)

        flow_grid = QGridLayout()
        flow_grid.setHorizontalSpacing(10)
        flow_grid.setVerticalSpacing(10)

        flow_steps = [
            (
                "1",
                "Import",
                "Yeni hand history dosyalarını ekle.",
                "Veri İçe Aktar",
                "import",
            ),
            (
                "2",
                "Bot Similarity",
                "750+ hand ve strateji filtreleriyle aday tara.",
                "Adayları Tara",
                "bot_similarity",
            ),
            (
                "3",
                "Player Explorer",
                "Kısa listedeki oyuncunun genel profilini aç.",
                "Oyuncuyu İncele",
                "player_explorer",
            ),
            (
                "4",
                "Bot DNA",
                "Tekrarlanan strateji ve sizing izlerini doğrula.",
                "DNA Analizi",
                "bot_dna",
            ),
            (
                "5",
                "Bot Group",
                "Doğrulanan benzer oyuncuları aynı grupta izle.",
                "Grubu Yönet",
                "bot_groups",
            ),
        ]

        for column, step in enumerate(flow_steps):
            flow_grid.addWidget(
                self._dashboard_step_card(*step),
                0,
                column,
            )
            flow_grid.setColumnStretch(column, 1)

        layout.addLayout(flow_grid)

        goal_title = QLabel("Başka ne araştırmak istiyorsun?")
        goal_title.setObjectName("DashboardSectionTitle")
        layout.addWidget(goal_title)

        goal_grid = QGridLayout()
        goal_grid.setHorizontalSpacing(10)
        goal_grid.setVerticalSpacing(10)

        goals = [
            (
                "Tek Oyuncu Profili",
                "Genel istatistikleri ve oyuncu eğilimlerini incele.",
                "Player Explorer'ı Aç",
                "player_explorer",
                "blue",
            ),
            (
                "Pool ve Open Size",
                "Pozisyon bazlı büyük open ve pool tepkilerini karşılaştır.",
                "Open Size Explorer'ı Aç",
                "open_size",
                "green",
            ),
            (
                "Board ve Sizing",
                "Board dokusuna göre sizing dağılımlarını araştır.",
                "Size × Board'u Aç",
                "size_board",
                "purple",
            ),
        ]

        for column, goal in enumerate(goals):
            goal_grid.addWidget(
                self._dashboard_goal_card(*goal),
                0,
                column,
            )
            goal_grid.setColumnStretch(column, 1)

        layout.addLayout(goal_grid)

        footer = QLabel(
            "DuckDB hazır • Benzerlik tek başına bot kanıtı değildir; "
            "adayları Player Explorer ve Bot DNA ile doğrula."
        )
        footer.setObjectName("InfoLabel")
        footer.setWordWrap(True)

        layout.addWidget(footer)
        layout.addStretch()

        return page

    def _dashboard_step_card(
        self,
        number: str,
        title: str,
        description: str,
        button_text: str,
        target_key: str,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("WorkflowStepCard")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 11, 12, 11)
        card_layout.setSpacing(6)

        badge = QLabel(number)
        badge.setObjectName("WorkflowStepBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(26, 26)

        title_label = QLabel(title)
        title_label.setObjectName("WorkflowStepTitle")

        description_label = QLabel(description)
        description_label.setObjectName("WorkflowStepDescription")
        description_label.setWordWrap(True)

        button = QPushButton(button_text)
        button.setObjectName("WorkflowStepButton")
        button.clicked.connect(
            lambda _checked=False, key=target_key: self.navigate_to(key)
        )

        card_layout.addWidget(badge)
        card_layout.addWidget(title_label)
        card_layout.addWidget(description_label, 1)
        card_layout.addWidget(button)
        return card

    def _dashboard_goal_card(
        self,
        title: str,
        description: str,
        button_text: str,
        target_key: str,
        accent: str,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("DashboardGoalCard")
        card.setProperty("accent", accent)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 11, 14, 11)
        card_layout.setSpacing(5)

        title_label = QLabel(title)
        title_label.setObjectName("DashboardGoalTitle")

        description_label = QLabel(description)
        description_label.setObjectName("DashboardGoalDescription")
        description_label.setWordWrap(True)

        button = QPushButton(button_text)
        button.setObjectName("DashboardGoalButton")
        button.clicked.connect(
            lambda _checked=False, key=target_key: self.navigate_to(key)
        )

        card_layout.addWidget(title_label)
        card_layout.addWidget(description_label, 1)
        card_layout.addWidget(button)
        return card

    def _start_recommended_analysis(self) -> None:
        if getattr(self, "dashboard_total_hands", 0) > 0:
            self.navigate_to("bot_similarity")
        else:
            self.navigate_to("import")

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

        phase = str(stats.get("phase") or "import")
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
        buffered = int(stats.get("buffered_hands", 0) or 0)
        batch_target = int(stats.get("batch_target", 0) or 0)
        write_seconds = float(stats.get("last_write_seconds", 0.0) or 0.0)
        if phase == "write":
            phase_text = f"DuckDB yazılıyor: {buffered:,} hand"
        elif phase == "commit":
            phase_text = f"Batch tamamlandı: {write_seconds:.1f} sn"
        elif phase == "scan":
            phase_text = "Dosyalar taranıyor"
        elif phase == "finished":
            phase_text = "Tamamlandı"
        else:
            phase_text = "Parse ediliyor"
        self.import_speed_label.setText(
            f"Turbo Import: {phase_text} • {rate:,.0f} hand/sn • "
            f"Parse: {parsed:,} • Cache: {cached} dosya • ETA {eta_text}"
            + (f" • Batch hedefi: {batch_target:,}" if batch_target else "")
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
        self._refresh_loaded_module("population")
        self._refresh_loaded_module("board_explorer")

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
        total_count = self.store.hand_count()
        player_count = self.store.player_count()
        action_count = self.store.action_count()

        self.dashboard_total_hands = total_count

        total = f"{total_count:,}".replace(",", ".")
        players = f"{player_count:,}".replace(",", ".")
        actions = f"{action_count:,}".replace(",", ".")

        self.total_hands_label.setText(
            f"Toplam Hand\n{total}"
        )
        self.total_players_label.setText(
            f"Toplam Oyuncu\n{players}"
        )
        self.total_actions_label.setText(
            f"Toplam Aksiyon\n{actions}"
        )

        if total_count > 0:
            self.dashboard_guidance_label.setText(
                f"{total} hand hazır. Filtreli bot adaylarını tarayarak "
                "araştırmaya devam et."
            )
            self.dashboard_primary_button.setText(
                "Bot Adayı Taramasını Başlat"
            )
        else:
            self.dashboard_guidance_label.setText(
                "Henüz analiz verisi yok. Önce hand history klasörünü seç "
                "ve import işlemini tamamla."
            )
            self.dashboard_primary_button.setText(
                "Hand History İçe Aktar"
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
                font-size: 19px;
                font-weight: 700;
                padding: 13px 16px;
                background: #23262d;
                border: 1px solid #343944;
                border-radius: 12px;
            }

            QFrame#WorkflowHero {
                background: #1c2540;
                border: 1px solid #3b5ccc;
                border-radius: 12px;
            }

            QLabel#WorkflowEyebrow {
                color: #7dd3fc;
                font-size: 11px;
                font-weight: 800;
            }

            QLabel#WorkflowTitle {
                color: #ffffff;
                font-size: 21px;
                font-weight: 800;
            }

            QLabel#WorkflowDescription,
            QLabel#WorkflowStepDescription,
            QLabel#DashboardGoalDescription {
                color: #aeb7c6;
                font-size: 12px;
            }

            QPushButton#WorkflowPrimaryButton {
                background: #4264dc;
                font-size: 14px;
                min-height: 44px;
            }

            QLabel#DashboardSectionTitle {
                color: #f3f4f6;
                font-size: 16px;
                font-weight: 750;
                padding-top: 2px;
            }

            QFrame#WorkflowStepCard,
            QFrame#DashboardGoalCard {
                background: #20242c;
                border: 1px solid #343b48;
                border-radius: 10px;
            }

            QFrame#DashboardGoalCard[accent="blue"] {
                border-top: 3px solid #38bdf8;
            }

            QFrame#DashboardGoalCard[accent="green"] {
                border-top: 3px solid #34d399;
            }

            QFrame#DashboardGoalCard[accent="purple"] {
                border-top: 3px solid #a78bfa;
            }

            QLabel#WorkflowStepBadge {
                background: #3154c9;
                border-radius: 13px;
                color: #ffffff;
                font-size: 12px;
                font-weight: 800;
            }

            QLabel#WorkflowStepTitle,
            QLabel#DashboardGoalTitle {
                color: #ffffff;
                font-size: 14px;
                font-weight: 750;
            }

            QPushButton#WorkflowStepButton,
            QPushButton#DashboardGoalButton {
                background: #2b313c;
                border: 1px solid #3d4655;
                min-height: 32px;
                padding: 0 9px;
                font-size: 12px;
            }

            QPushButton#WorkflowStepButton:hover,
            QPushButton#DashboardGoalButton:hover {
                background: #364156;
                border-color: #5473e8;
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
