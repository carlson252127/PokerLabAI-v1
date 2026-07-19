IMPORT TURBO V1
===============

Kurulum:
1. PokerLab AI kapalı olsun.
2. ZIP'i C:\Users\user\Desktop\PokerLabAI_v1 içine çıkar.
3. PowerShell:

   cd C:\Users\user\Desktop\PokerLabAI_v1
   py ImportTurboV1\install_import_turbo_v1.py
   py main.py

Hızlandırmalar:
- Değişmeyen HH dosyalarını file size + modified time cache ile tamamen atlar.
- 25.000 hand'e kadar dosyaları tek Arrow/DuckDB batch'inde toplar.
- DuckDB bağlantısını import boyunca açık tutar.
- Her batch'i tek transaction ile yazar.
- Mevcut hand ID'lerde child row delete/reinsert yapmaz; duplicate'leri hızlıca atlar.
- CPU'ya göre 4-16 DuckDB thread kullanır.
- preserve_insertion_order kapalıdır.
- UI'da hands/sec, parse edilen hand, cache dosyası ve ETA gösterir.

Not:
İlk import yine bütün dosyaları okur. En büyük hız farkı ikinci ve sonraki importlarda görülür.
Bir dosya değişirse yalnızca o dosya yeniden parse edilir.
