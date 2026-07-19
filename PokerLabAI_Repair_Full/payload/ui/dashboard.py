from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout


class DashboardPage(QWidget):

    def __init__(self):
        super().__init__()

        layout = QVBoxLayout(self)

        title = QLabel("PokerLab AI")
        title.setStyleSheet("""
        font-size:30px;
        font-weight:bold;
        color:white;
        """)

        info = QLabel("""
CoinPoker Blueprint

Toplam Bot : 107

Toplam Hand : 1.100.000

Version : 0.2
""")

        info.setStyleSheet("""
        color:white;
        font-size:18px;
        """)

        layout.addWidget(title)
        layout.addWidget(info)
        layout.addStretch()

        self.setStyleSheet("""
        background:#313338;
        border-radius:10px;
        """)