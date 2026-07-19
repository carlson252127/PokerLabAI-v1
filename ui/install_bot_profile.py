from __future__ import annotations

from pathlib import Path
import shutil


def main() -> int:
    root = Path(__file__).resolve().parent
    target = root / "ui" / "main_window.py"

    if not target.exists():
        print("HATA: ui/main_window.py bulunamadı.")
        return 1

    backup = root / "ui" / "main_window_before_bot_profile.py"
    if not backup.exists():
        shutil.copy2(target, backup)

    text = target.read_text(encoding="utf-8")

    import_line = "from ui.bot_profile_explorer import BotProfileExplorer\n"
    if import_line not in text:
        anchor = "from ui.open_size_explorer import OpenSizeExplorer\n"
        if anchor not in text:
            raise RuntimeError("OpenSizeExplorer import satırı bulunamadı.")
        text = text.replace(anchor, anchor + import_line, 1)

    if '"Bot Profile Report"' not in text:
        anchor = '                "Open Size Explorer",\n'
        if anchor not in text:
            raise RuntimeError("Open Size Explorer menü satırı bulunamadı.")
        text = text.replace(
            anchor,
            anchor + '                "Bot Profile Report",\n',
            1,
        )

    instance = (
        "        self.bot_profile_page = BotProfileExplorer(\n"
        "            self.store.database_path\n"
        "        )\n"
    )

    if "self.bot_profile_page = BotProfileExplorer" not in text:
        anchor = (
            "        self.open_size_page = OpenSizeExplorer(\n"
            "            self.store.database_path\n"
            "        )\n"
        )
        if anchor not in text:
            raise RuntimeError("Open Size Explorer oluşturma bölümü bulunamadı.")
        text = text.replace(anchor, anchor + instance, 1)

    page_line = "        self.pages.addWidget(self.bot_profile_page)\n"
    if page_line not in text:
        anchor = "        self.pages.addWidget(self.open_size_page)\n"
        if anchor not in text:
            raise RuntimeError("Open Size Explorer sayfa bölümü bulunamadı.")
        text = text.replace(anchor, anchor + page_line, 1)

    start = text.find("        if index == 2:\n")
    end = text.find("\n    def _dashboard_page", start)

    if start == -1 or end == -1:
        raise RuntimeError("_change_page bölümü bulunamadı.")

    refresh = (
        "        if index == 2:\n"
        "            self.population_page.refresh_filters()\n\n"
        "        if index == 3:\n"
        "            self.player_explorer_page.refresh_filters()\n\n"
        "        if index == 4:\n"
        "            self.alias_manager_page.refresh_aliases()\n\n"
        "        if index == 5:\n"
        "            self.bot_similarity_page.refresh_filters()\n\n"
        "        if index == 6:\n"
        "            self.open_size_page.refresh_filters()\n\n"
        "        if index == 7:\n"
        "            self.bot_profile_page.refresh_filters()\n\n"
        "        if index == 8:\n"
        "            self.board_explorer_page.refresh_filters()\n\n"
        "        if index == 9:\n"
        "            self.mda_matrix_page.refresh_filters()\n\n"
        "        if index == 10:\n"
        "            self.gto_import_page.refresh_filters()\n\n"
        "        if index == 11:\n"
        "            self.exploit_report_page.refresh_filters()\n\n"
        "        if index == 12:\n"
        "            self.ai_coach_page.refresh_filters()\n"
    )

    text = text[:start] + refresh + text[end:]
    target.write_text(text, encoding="utf-8")

    print("Bot Profile Report eklendi.")
    print(f"Yedek: {backup}")
    print("Şimdi: py main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
