from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sys

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
REQUIRED = PROJECT_DIR / "main.py"

if not REQUIRED.exists():
    print("HATA: Bu klasörü PokerLabAI_v1 proje klasörünün içine çıkar.")
    print(f"Beklenen dosya: {REQUIRED}")
    sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = PROJECT_DIR / "backups" / f"board_intelligence_megapack_{stamp}"
files = [
    ("ui/size_board_strategy_explorer.py", "ui/size_board_strategy_explorer.py"),
    ("ui/board_matchup_explorer.py", "ui/board_matchup_explorer.py"),
    ("services/gto_reference_service.py", "services/gto_reference_service.py"),
]

for source_rel, target_rel in files:
    source = PACKAGE_DIR / source_rel
    target = PROJECT_DIR / target_rel
    if target.exists():
        saved = backup / target_rel
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, saved)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    print(f"KURULDU: {target_rel}")

print("\nKurulum tamamlandı.")
print(f"Yedek: {backup}")
print("Başlat: py main.py")
