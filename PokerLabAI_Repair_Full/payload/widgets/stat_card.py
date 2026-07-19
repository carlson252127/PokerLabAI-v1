from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout
from PySide6.QtCore import Qt


class StatCard(QFrame):
    def __init__(self, title, value):
        super().__init__()

        self.setObjectName("StatCard")

        layout = QVBoxLayout(self)

        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignCenter)

        self.value = QLabel(value)
        self.value.setAlignment(Qt.AlignCenter)

        self.title.setObjectName("CardTitle")
        self.value.setObjectName("CardValue")

        layout.addWidget(self.title)
        layout.addWidget(self.value)

        self.setStyleSheet("""
        QFrame#StatCard{
            background:#2B2D31;
            border:1px solid #3F4248;
            border-radius:12px;
            min-width:220px;
            min-height:120px;
        }

        QLabel#CardTitle{
            color:#A0A0A0;
            font-size:14px;
        }

        QLabel#CardValue{
            color:white;
            font-size:28px;
            font-weight:bold;
        }
        """)