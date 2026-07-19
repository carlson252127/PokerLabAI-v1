from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def _load_stylesheet(app: QApplication) -> None:
    style_path = Path(__file__).resolve().parent / "styles" / "dark.qss"
    if style_path.exists():
        app.setStyleSheet(style_path.read_text(encoding="utf-8"))


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PokerLab AI")
    app.setOrganizationName("PokerLab")
    app.setStyle("Fusion")
    _load_stylesheet(app)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
