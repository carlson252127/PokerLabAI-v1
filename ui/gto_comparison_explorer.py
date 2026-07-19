from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.gto_comparison_service import GTOComparisonService
from services.spot_engine import SpotEngine


class GTOComparisonExplorer(QWidget):
    POSITIONS = ["BTN", "CO", "HJ", "UTG", "SB", "BB"]

    BOARD_TEXTURES = [
        ("Tüm Boardlar", ""),
        ("A-High Rainbow", "A_HIGH_RAINBOW"),
        ("A-High Two-Tone", "A_HIGH_TWO_TONE"),
        ("A-High Monotone", "A_HIGH_MONOTONE"),
        ("K-High Rainbow", "K_HIGH_RAINBOW"),
        ("K-High Two-Tone", "K_HIGH_TWO_TONE"),
        ("Q-High Rainbow", "Q_HIGH_RAINBOW"),
        ("Low Rainbow", "LOW_RAINBOW"),
        ("Low Two-Tone", "LOW_TWO_TONE"),
        ("Paired", "PAIRED"),
        ("Trips", "TRIPS"),
        ("Connected", "CONNECTED"),
        ("Rainbow", "RAINBOW"),
        ("Two-Tone", "TWO_TONE"),
        ("Monotone", "MONOTONE"),
    ]

    def __init__(
        self,
        database_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self.service = GTOComparisonService(database_path)
        self.filters_loaded = False

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        title = QLabel("Pool vs GTO — Position Engine")
        title.setObjectName("PageTitle")

        subtitle = QLabel(
            "Pozisyonsuz veya pozisyonlu analiz; IP/OOP, pot tipi "
            "ve board texture bazında karşılaştırma."
        )
        subtitle.setObjectName("PageSubtitle")

        root.addWidget(title)
        root.addWidget(subtitle)

        form = QFrame()
        form.setObjectName("CompareForm")

        grid = QGridLayout(form)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        self.site_combo = QComboBox()
        self.site_combo.addItem("Tüm Siteler", "")

        self.stakes_combo = QComboBox()
        self.stakes_combo.addItem("Tüm Limitler", "")

        self.hero_position_combo = QComboBox()
        self.hero_position_combo.addItem("Tüm Pozisyonlar", "")
        for position in self.POSITIONS:
            self.hero_position_combo.addItem(position, position)

        self.villain_position_combo = QComboBox()
        self.villain_position_combo.addItem("Tüm Rakip Poz.", "")
        for position in self.POSITIONS:
            self.villain_position_combo.addItem(position, position)

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
        for label, value in self.BOARD_TEXTURES:
            self.texture_combo.addItem(label, value)

        self.stat_combo = QComboBox()
        for label, key in SpotEngine.SUPPORTED_STATS.items():
            self.stat_combo.addItem(label, key)

        self.gto_spin = QDoubleSpinBox()
        self.gto_spin.setRange(0.0, 100.0)
        self.gto_spin.setDecimals(2)
        self.gto_spin.setSuffix(" %")

        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Solver kaynağı / not")

        labels = [
            "Site",
            "Stakes",
            "Hero Poz.",
            "Rakip Poz.",
            "Konum",
            "Pot Tipi",
            "Board",
            "Stat",
            "GTO",
        ]

        widgets = [
            self.site_combo,
            self.stakes_combo,
            self.hero_position_combo,
            self.villain_position_combo,
            self.location_combo,
            self.pot_type_combo,
            self.texture_combo,
            self.stat_combo,
            self.gto_spin,
        ]

        for index, (label, widget) in enumerate(zip(labels, widgets)):
            grid.addWidget(QLabel(label), 0, index)
            grid.addWidget(widget, 1, index)

        grid.addWidget(QLabel("Not"), 2, 0)
        grid.addWidget(self.note_input, 3, 0, 1, 5)

        self.calculate_button = QPushButton("Karşılaştır")
        self.save_button = QPushButton("GTO Kaydet")

        self.calculate_button.clicked.connect(
            self.calculate_comparison
        )
        self.save_button.clicked.connect(
            self.save_baseline
        )

        button_row = QHBoxLayout()
        button_row.addWidget(self.calculate_button)
        button_row.addWidget(self.save_button)
        button_row.addStretch()

        grid.addLayout(button_row, 3, 5, 1, 4)

        root.addWidget(form)

        cards = QHBoxLayout()
        cards.setSpacing(12)

        self.pool_card = self._card("Pool", "—")
        self.gto_card = self._card("GTO", "—")
        self.delta_card = self._card("Delta", "—")
        self.sample_card = self._card("Sample", "—")

        cards.addWidget(self.pool_card)
        cards.addWidget(self.gto_card)
        cards.addWidget(self.delta_card)
        cards.addWidget(self.sample_card)

        root.addLayout(cards)

        self.spot_label = QLabel("Spot: Genel")
        self.spot_label.setObjectName("SpotLabel")
        root.addWidget(self.spot_label)

        self.interpretation = QLabel(
            "Filtreleri seçip Karşılaştır düğmesine bas."
        )
        self.interpretation.setWordWrap(True)
        self.interpretation.setObjectName("Interpretation")
        root.addWidget(self.interpretation)

        root.addStretch()

        for combo in (
            self.site_combo,
            self.stakes_combo,
            self.hero_position_combo,
            self.villain_position_combo,
            self.location_combo,
            self.pot_type_combo,
            self.texture_combo,
            self.stat_combo,
        ):
            combo.currentIndexChanged.connect(
                self.load_baseline
            )

        self.setStyleSheet(
            """
            QFrame#CompareForm {
                background: #171b24;
                border: 1px solid #303744;
                border-radius: 12px;
            }

            QFrame#CompareCard {
                background: #1d222d;
                border: 1px solid #343b49;
                border-radius: 12px;
            }

            QLabel#CompareCardTitle {
                color: #9ca3af;
                font-size: 13px;
            }

            QLabel#CompareCardValue {
                font-size: 28px;
                font-weight: 800;
            }

            QLabel#SpotLabel,
            QLabel#Interpretation {
                padding: 16px;
                background: #23262d;
                border: 1px solid #343944;
                border-radius: 12px;
                font-size: 15px;
                font-weight: 600;
            }
            """
        )

    def _card(self, title: str, value: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("CompareCard")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 14, 18, 14)

        title_label = QLabel(title)
        title_label.setObjectName("CompareCardTitle")

        value_label = QLabel(value)
        value_label.setObjectName("CompareCardValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        frame.value_label = value_label

        layout.addWidget(title_label)
        layout.addWidget(value_label)

        return frame

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
            self.load_baseline()

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Filtre Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def _keys(
        self,
    ) -> tuple[str, str, str, str, str, str, str, str]:
        return (
            str(self.site_combo.currentData() or "ALL"),
            str(self.stakes_combo.currentData() or "ALL"),
            str(self.hero_position_combo.currentData() or "ALL"),
            str(self.villain_position_combo.currentData() or "ALL"),
            str(self.location_combo.currentData() or "ALL"),
            str(self.pot_type_combo.currentData() or "ALL"),
            str(self.texture_combo.currentData() or "ALL"),
            str(self.stat_combo.currentData()),
        )

    def load_baseline(self) -> None:
        (
            site,
            stakes,
            hero_position,
            villain_position,
            location,
            pot_type,
            board_texture,
            stat_key,
        ) = self._keys()

        try:
            value = self.service.get_baseline(
                site,
                stakes,
                hero_position,
                villain_position,
                location,
                pot_type,
                board_texture,
                stat_key,
            )

            if value is None:
                self.gto_spin.setValue(0.0)
            else:
                self.gto_spin.setValue(value)

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Filtre Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def save_baseline(self) -> None:
        (
            site,
            stakes,
            hero_position,
            villain_position,
            location,
            pot_type,
            board_texture,
            stat_key,
        ) = self._keys()

        try:
            self.service.save_baseline(
                site=site,
                stakes=stakes,
                hero_position=hero_position,
                villain_position=villain_position,
                location=location,
                pot_type=pot_type,
                board_texture=board_texture,
                stat_key=stat_key,
                gto_value=self.gto_spin.value(),
                note=self.note_input.text().strip(),
            )

            QMessageBox.information(
                self,
                "GTO Kaydedildi",
                "Bu spot için GTO referansı kaydedildi.",
            )

        except Exception as exc:
            QMessageBox.critical(
                self,
                "GTO Kayıt Hatası",
                f"{type(exc).__name__}: {exc}",
            )

    def calculate_comparison(self) -> None:
        site = str(self.site_combo.currentData() or "")
        stakes = str(self.stakes_combo.currentData() or "")
        hero_position = str(
            self.hero_position_combo.currentData() or ""
        )
        villain_position = str(
            self.villain_position_combo.currentData() or ""
        )
        location = str(
            self.location_combo.currentData() or ""
        )
        pot_type = str(
            self.pot_type_combo.currentData() or ""
        )
        board_texture = str(
            self.texture_combo.currentData() or ""
        )
        stat_key = str(self.stat_combo.currentData())

        try:
            pool, numerator, denominator = (
                self.service.calculate_population_stat(
                    stat_key=stat_key,
                    site=site,
                    stakes=stakes,
                    hero_position=hero_position,
                    villain_position=villain_position,
                    location=location,
                    pot_type=pot_type,
                    board_texture=board_texture,
                )
            )

            gto = self.gto_spin.value()
            delta = pool - gto

            self.pool_card.value_label.setText(
                f"{pool:.2f}%"
            )
            self.gto_card.value_label.setText(
                f"{gto:.2f}%"
            )
            self.delta_card.value_label.setText(
                f"{delta:+.2f}%"
            )
            self.sample_card.value_label.setText(
                f"{numerator:,}/{denominator:,}"
            )

            spot_parts = [
                hero_position or "Tüm Pozisyonlar",
            ]

            if villain_position:
                spot_parts.append(f"vs {villain_position}")

            spot_parts.append(location or "IP + OOP")
            spot_parts.append(pot_type or "Tüm Potlar")
            spot_parts.append(
                self.texture_combo.currentText()
            )
            spot_parts.append(
                self.stat_combo.currentText()
            )

            self.spot_label.setText(
                "Spot: " + " — ".join(spot_parts)
            )

            if denominator == 0:
                message = (
                    "Bu filtre kombinasyonunda opportunity bulunamadı."
                )
            elif abs(delta) < 2.0:
                message = (
                    "Pool ve GTO birbirine yakın. "
                    "Belirgin exploit sinyali yok."
                )
            elif delta > 0:
                message = (
                    f"Pool bu hamleyi GTO'dan {delta:.2f} puan "
                    "daha fazla kullanıyor."
                )
            else:
                message = (
                    f"Pool bu hamleyi GTO'dan {abs(delta):.2f} puan "
                    "daha az kullanıyor."
                )

            if denominator < 500:
                message += " Sample düşük; temkinli yorumla."

            self.interpretation.setText(message)

        except Exception as exc:
            QMessageBox.critical(
                self,
                "Karşılaştırma Hatası",
                f"{type(exc).__name__}: {exc}",
            )
