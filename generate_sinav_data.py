"""LGS Sınav test verisi oluşturma scripti"""
import database as db
import random
from datetime import date, timedelta

db.init_db()

# Kurumları ekle
kurum_isimleri = ["Özdebir", "Sinan Kuzucu", "Çözüm Yayınları", "Limit Yayınları", "Başarı Sıralama"]
for kurum in kurum_isimleri:
    db.kurum_ekle(kurum)

kurumlar = db.kurumlari_getir()
kurum_ids = {k["kurum_adi"]: k["id"] for k in kurumlar}

# LGS ders bilgileri
lgs_dersler = {
    "Türkçe": 20, "Matematik": 20, "Fen": 20,
    "Sosyal": 10, "İngilizce": 10, "Din": 10
}

random.seed(123)

# Son 4 ayda ~12 sınav oluştur
sinav_listesi = [
    ("Özdebir TYT-1", "2026-01-10", "Özdebir"),
    ("Sinan Kuzucu Deneme-1", "2026-01-18", "Sinan Kuzucu"),
    ("Çözüm Deneme-1", "2026-01-25", "Çözüm Yayınları"),
    ("Özdebir TYT-2", "2026-02-07", "Özdebir"),
    ("Limit Deneme-1", "2026-02-15", "Limit Yayınları"),
    ("Sinan Kuzucu Deneme-2", "2026-02-22", "Sinan Kuzucu"),
    ("Başarı Sıralama-1", "2026-03-01", "Başarı Sıralama"),
    ("Özdebir TYT-3", "2026-03-08", "Özdebir"),
    ("Çözüm Deneme-2", "2026-03-15", "Çözüm Yayınları"),
    ("Sinan Kuzucu Deneme-3", "2026-03-22", "Sinan Kuzucu"),
    ("Limit Deneme-2", "2026-04-05", "Limit Yayınları"),
    ("Özdebir TYT-4", "2026-04-12", "Özdebir"),
]

# Zamanla iyileşen başarı profili
for i, (sinav_adi, tarih, kurum_adi) in enumerate(sinav_listesi):
    ilerleme = i * 0.02  # Her sınavda biraz daha iyi

    # Ders bazında sonuçlar
    toplam_net = 0
    ders_sonuclari = []

    for ders, soru_sayisi in lgs_dersler.items():
        # Ders bazında farklı başarı oranları
        base_basari = {
            "Türkçe": 0.75, "Matematik": 0.55, "Fen": 0.62,
            "Sosyal": 0.80, "İngilizce": 0.72, "Din": 0.85
        }

        basari = min(0.98, base_basari[ders] + ilerleme + random.uniform(-0.08, 0.08))
        dogru = int(soru_sayisi * basari)
        dogru = max(0, min(soru_sayisi, dogru))
        yanlis = random.randint(0, soru_sayisi - dogru)
        net = dogru - (yanlis / 3.0)
        toplam_net += net

        ders_sonuclari.append((ders, soru_sayisi, dogru, yanlis))

    # Puan hesapla (basit yaklaşım: toplam_net * 5 + 200 civarı)
    puan = 200 + (toplam_net * 4.2) + random.uniform(-10, 10)
    puan = min(500, max(100, round(puan, 3)))

    # Dereceler (zamanla iyileşen)
    genel = max(1, int(5000 - i * 350 + random.randint(-200, 200)))
    il_d = max(1, int(1200 - i * 90 + random.randint(-50, 50)))
    ilce = max(1, int(300 - i * 22 + random.randint(-15, 15)))
    kurum_d = max(1, int(50 - i * 3 + random.randint(-5, 5)))
    sube = max(1, int(10 - i * 0.5 + random.randint(-2, 2)))

    # Sınav kaydet
    sinav_id = db.sinav_ekle(
        sinav_adi, tarih, kurum_ids[kurum_adi],
        puan, genel, il_d, ilce, kurum_d, sube
    )

    # Ders sonuçlarını kaydet
    for ders, ss, d, y in ders_sonuclari:
        db.sinav_ders_ekle(sinav_id, ders, ss, d, y)

print(f"{len(sinav_listesi)} sınav kaydı oluşturuldu!")
print(f"{len(kurum_isimleri)} kurum eklendi: {', '.join(kurum_isimleri)}")

# Özet
print("\nSınav Özeti:")
print(f"{'Sınav':<30} {'Tarih':<12} {'Kurum':<18} {'Puan':>8}")
print("-" * 72)

sinavlar = db.sinavlari_getir()
for s in reversed(sinavlar):
    puan_str = f"{s['puan']:.1f}" if s["puan"] else "-"
    kurum_str = s["kurum_adi"] or "-"
    print(f"{s['sinav_adi']:<30} {s['sinav_tarihi']:<12} {kurum_str:<18} {puan_str:>8}")
