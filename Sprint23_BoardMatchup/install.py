from __future__ import annotations

from datetime import datetime
from pathlib import Path
import py_compile
import shutil
import sys


def locate_project() -> Path:
    candidates = [Path.cwd(), Path(__file__).resolve().parent.parent, Path(__file__).resolve().parent]
    for candidate in candidates:
        if (candidate / "main.py").exists() and (candidate / "ui" / "main_window.py").exists():
            return candidate.resolve()
    raise SystemExit(
        "HATA: PokerLab proje klasörü bulunamadı.\n"
        "ZIP'i PokerLabAI_v1 içine çıkar ve şu komutu proje klasöründe çalıştır:\n"
        "py Sprint23_BoardMatchup\\install.py"
    )


def backup_file(project: Path, backup_root: Path, relative: Path) -> None:
    source = project / relative
    if not source.exists():
        return
    target = backup_root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def patch_main_window(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    import_line = "from ui.board_matchup_explorer import BoardMatchupExplorer\n"
    if import_line not in text:
        anchors = [
            "from ui.response_comparison_explorer import ResponseComparisonExplorer\n",
            "from ui.response_explorer import ResponseExplorer\n",
        ]
        for anchor in anchors:
            if anchor in text:
                text = text.replace(anchor, anchor + import_line, 1)
                break
        else:
            raise RuntimeError("main_window.py içinde uygun import noktası bulunamadı.")

    init_code = (
        "        self.board_matchup_page = BoardMatchupExplorer(\n"
        "            self.store.database_path\n"
        "        )\n"
    )
    if "self.board_matchup_page = BoardMatchupExplorer(" not in text:
        anchors = [
            "        self.response_comparison_page = ResponseComparisonExplorer(\n            self.store.database_path\n        )\n",
            "        self.response_explorer_page = ResponseExplorer(\n            self.store.database_path\n        )\n",
        ]
        for anchor in anchors:
            if anchor in text:
                text = text.replace(anchor, anchor + init_code, 1)
                break
        else:
            raise RuntimeError("main_window.py içinde sayfa oluşturma noktası bulunamadı.")

    registry_line = (
        '            ("Open Size Lab", "board_matchup", "Board Matchup & Pool Response", '
        'self.board_matchup_page, self._refresh_callback(self.board_matchup_page, "refresh_filters"), '
        '("board", "matchup", "human", "pool", "cbet", "fold", "overbet")),\n'
    )
    if '"board_matchup"' not in text:
        anchors = [
            '            ("Open Size Lab", "response_compare", "Bot vs Pool Response", self.response_comparison_page, self._refresh_callback(self.response_comparison_page, "refresh_filters"), ("bot", "pool", "pressure", "comparison")),\n',
            '            ("Open Size Lab", "pool_response", "Pool Response Explorer", self.response_explorer_page, self._refresh_callback(self.response_explorer_page, "refresh_filters"), ("response", "fold", "3bet")),\n',
        ]
        for anchor in anchors:
            if anchor in text:
                text = text.replace(anchor, anchor + registry_line, 1)
                break
        else:
            raise RuntimeError("main_window.py içinde Open Size Lab registry noktası bulunamadı.")

    path.write_text(text, encoding="utf-8")


def main() -> None:
    project = locate_project()
    package = Path(__file__).resolve().parent
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = project / "backups" / f"sprint23_board_matchup_{stamp}"

    files = [
        Path("services/board_matchup_service.py"),
        Path("ui/board_matchup_explorer.py"),
        Path("ui/main_window.py"),
    ]
    for relative in files:
        backup_file(project, backup_root, relative)

    for relative in [Path("services/board_matchup_service.py"), Path("ui/board_matchup_explorer.py")]:
        source = package / relative
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    patch_main_window(project / "ui" / "main_window.py")

    compile_targets = [
        project / "services" / "board_matchup_service.py",
        project / "ui" / "board_matchup_explorer.py",
        project / "ui" / "main_window.py",
    ]
    for target in compile_targets:
        py_compile.compile(str(target), doraise=True)

    print("\nSprint 2 + 3 kurulumu tamamlandı.")
    print(f"Proje: {project}")
    print(f"Yedek: {backup_root}")
    print("Yeni ekran: Open Size Lab > Board Matchup & Pool Response")
    print("Programı başlat: py main.py\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"HATA: {type(exc).__name__}: {exc}")
        sys.exit(1)
