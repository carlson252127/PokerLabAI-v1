POKERLAB AI — BOARD INTELLIGENCE MEGA PACK

KURULUM
1) ZIP içindeki PokerLabAI_BoardIntelligence_MegaPack klasörünü
   C:\Users\user\Desktop\PokerLabAI_v1 içine çıkar.
2) PowerShell:
   cd C:\Users\user\Desktop\PokerLabAI_v1
   py PokerLabAI_BoardIntelligence_MegaPack\install.py
   py main.py

EKLENENLER
1. Size × Board ekranında size bağımsız Board Total + GTO Sapma paneli.
2. Tüm görünür kart limitinden bağımsız opportunity-ağırlıklı Flop/Turn/River toplamları.
3. Bet, Check, gerçek frekans, ortalama bet size ve toplam sample.
4. Board-family filtresiyle total sonuçları yeniden hesaplama.
5. Elle GTO Bet frekansı girişi ve kalıcı JSON kayıt.
6. Gerçek − GTO yüzde-puan sapması.
7. Board Matchup ekranında GTO Bet ve GTO Fold kolonları.
8. Bot−GTO, Human Pool−GTO ve Human Fold−GTO sapmaları.
9. GTO değerlerinin site + stakes + board family + street bazında saklanması.
10. Daha genel referanslara otomatik fallback.

NOT
- Database ve hand history verilerine dokunmaz.
- Değiştirilen dosyaları backups klasörüne otomatik yedekler.
- GTO değerleri database/gto_board_references.json içinde tutulur.
