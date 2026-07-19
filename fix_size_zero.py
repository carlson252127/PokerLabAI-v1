from __future__ import annotations

from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "sitecustomize.py"

NEW_CONTENT = """from __future__ import annotations

# PokerLab AI ortak board sınıflandırma uyumluluğu.
# Size hesaplayan servis metotlarına dokunulmaz; yalnızca eksik board
# yardımcıları geriye dönük olarak eklenir.

def _install_service_compatibility() -> None:
    try:
        from services.board_taxonomy import board_family, simple_family, turn_transition
        from services.size_board_strategy_service import SizeBoardStrategyService

        if not hasattr(SizeBoardStrategyService, "_texture_family"):
            SizeBoardStrategyService._texture_family = staticmethod(board_family)

        if not hasattr(SizeBoardStrategyService, "_simple_flop_family"):
            SizeBoardStrategyService._simple_flop_family = staticmethod(simple_family)

        if not hasattr(SizeBoardStrategyService, "_turn_transition"):
            SizeBoardStrategyService._turn_transition = staticmethod(turn_transition)

    except Exception:
        pass


def _install_ui_hooks() -> None:
    try:
        from PySide6.QtWidgets import QComboBox, QTableWidget
        from ui.analytics_palette import style_combo, style_table

        original_show_popup = QComboBox.showPopup

        def colored_show_popup(self):
            try:
                style_combo(self)
            except Exception:
                pass
            return original_show_popup(self)

        QComboBox.showPopup = colored_show_popup

        original_resize_rows = QTableWidget.resizeRowsToContents

        def colored_resize_rows(self):
            try:
                style_table(self)
            except Exception:
                pass
            return original_resize_rows(self)

        QTableWidget.resizeRowsToContents = colored_resize_rows

    except Exception:
        pass


_install_service_compatibility()
_install_ui_hooks()
"""

def main() -> int:
    if not SITE.exists():
        print(f"HATA: {SITE} bulunamadı.")
        return 1

    backup = ROOT / "sitecustomize_before_size_zero_fix.py"
    shutil.copy2(SITE, backup)
    SITE.write_text(NEW_CONTENT, encoding="utf-8")

    for cache in ROOT.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    print("DÜZELTİLDİ: sitecustomize.py")
    print("KALDIRILDI: _size_bucket / _study_size_bucket monkey patch")
    print(f"YEDEK: {backup.name}")
    print()
    print("Şimdi çalıştır:")
    print("python -c \"import sitecustomize; print('sitecustomize OK')\"")
    print("python main.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
