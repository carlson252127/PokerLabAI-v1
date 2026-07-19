from __future__ import annotations

def _install_service_compatibility() -> None:
    try:
        from services.board_taxonomy import board_family, simple_family, turn_transition
        from services.size_bucket_service import open_bucket
        from services.size_board_strategy_service import SizeBoardStrategyService

        SizeBoardStrategyService._texture_family = staticmethod(board_family)
        SizeBoardStrategyService._simple_flop_family = staticmethod(simple_family)
        SizeBoardStrategyService._turn_transition = staticmethod(turn_transition)

        for method_name in ("_size_bucket", "_study_size_bucket"):
            if hasattr(SizeBoardStrategyService, method_name):
                setattr(
                    SizeBoardStrategyService,
                    method_name,
                    staticmethod(lambda value, *_args, **_kwargs: open_bucket(float(value or 0))),
                )
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
