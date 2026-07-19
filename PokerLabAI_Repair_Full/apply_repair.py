from pathlib import Path
import shutil, datetime, sys

project = Path.cwd()
payload = Path(__file__).resolve().parent / 'payload'
if not (project / 'main.py').exists():
    print(f'HATA: Bu komutu PokerLabAI_v1 klasöründe çalıştırın. main.py bulunamadı: {project / "main.py"}')
    sys.exit(1)

stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
backup = project / 'backups' / f'full_repair_{stamp}'
backup.mkdir(parents=True, exist_ok=True)

for name in ['main.py','requirements.txt','models','services','styles','ui','widgets']:
    src = project / name
    if src.exists():
        dst = backup / name
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

for item in payload.iterdir():
    dst = project / item.name
    if item.is_dir():
        shutil.copytree(item, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(item, dst)

print('TAMAM: Kaynak dosyalar geri yüklendi ve Import Turbo düzeltmesi uygulandı.')
print(f'Yedek: {backup}')
print('Şimdi çalıştırın: py main.py')
