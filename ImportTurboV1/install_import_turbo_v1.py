from __future__ import annotations
from datetime import datetime
from pathlib import Path
import shutil, py_compile

PATCH = Path(__file__).resolve().parent
ROOT = PATCH.parent
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "backups" / f"import_turbo_v1_{STAMP}"
FILES = [
    "services/analytical_store.py",
    "services/import_worker.py",
    "ui/main_window.py",
]

def main() -> int:
    if not (ROOT / "main.py").exists():
        print("HATA: ImportTurboV1 klasörünü PokerLabAI_v1 ana klasörüne çıkar.")
        return 1
    for rel in FILES:
        src = PATCH / rel
        dst = ROOT / rel
        if dst.exists():
            backup = BACKUP / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        py_compile.compile(str(dst), doraise=True)
    print("Import Turbo V1 kuruldu.")
    print(f"Yedek: {BACKUP}")
    print("Çalıştır: py main.py")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
