"""Test verisi oluşturma scripti - Son 4 ay için simülasyon"""
import database as db
import random
from datetime import date, timedelta

db.init_db()

# Son 4 ay için tarih aralığını hesapla
bugun = date(2026, 4, 18)
baslangic = date(2025, 12, 18)

# Ders bazında soru havuzu ve zorluk profilleri
ders_profil = {
    "Türkçe":    {"min_soru": 5, "max_soru": 30, "basari_ort": 0.72, "trend": 0.002},
    "Matematik": {"min_soru": 5, "max_soru": 25, "basari_ort": 0.60, "trend": 0.003},
    "Fen":       {"min_soru": 5, "max_soru": 25, "basari_ort": 0.65, "trend": 0.0025},
    "Sosyal":    {"min_soru": 3, "max_soru": 20, "basari_ort": 0.75, "trend": 0.002},
    "İngilizce": {"min_soru": 3, "max_soru": 15, "basari_ort": 0.70, "trend": 0.0015},
    "Din":       {"min_soru": 3, "max_soru": 15, "basari_ort": 0.78, "trend": 0.001},
}

random.seed(42)
toplam_kayit = 0
gun_sayisi = (bugun - baslangic).days

for gun_offset in range(gun_sayisi + 1):
    tarih = baslangic + timedelta(days=gun_offset)

    # Hafta sonu biraz daha fazla çalış
    hafta_sonu = tarih.weekday() >= 5

    # Bazı günler çalışılmamış olabilir (%8 şans)
    if random.random() < 0.08 and not hafta_sonu:
        continue

    # Her gün 2-5 ders arası çalış
    if hafta_sonu:
        ders_sayisi = random.randint(3, 6)
    else:
        ders_sayisi = random.randint(2, 5)

    secilen_dersler = random.sample(list(ders_profil.keys()), min(ders_sayisi, 6))

    for ders_adi in secilen_dersler:
        profil = ders_profil[ders_adi]

        # İlerleme faktörünü hesapla (zamanla iyileşme)
        ilerleme = gun_offset * profil["trend"]
        basari_orani = min(0.95, profil["basari_ort"] + ilerleme + random.uniform(-0.1, 0.1))

        soru = random.randint(profil["min_soru"], profil["max_soru"])

        # Hafta sonu daha fazla soru
        if hafta_sonu:
            soru = int(soru * random.uniform(1.2, 1.6))

        dogru = int(soru * basari_orani)
        dogru = max(0, min(soru, dogru))
        yanlis = random.randint(0, soru - dogru)

        db.kayit_ekle(tarih.strftime("%Y-%m-%d"), ders_adi, soru, dogru, yanlis)
        toplam_kayit += 1

        # Bazen aynı gün aynı dersten 2. kez çözmüş olabilir (%15)
        if random.random() < 0.15:
            soru2 = random.randint(profil["min_soru"], profil["max_soru"])
            dogru2 = int(soru2 * basari_orani)
            dogru2 = max(0, min(soru2, dogru2))
            yanlis2 = random.randint(0, soru2 - dogru2)
            db.kayit_ekle(tarih.strftime("%Y-%m-%d"), ders_adi, soru2, dogru2, yanlis2)
            toplam_kayit += 1

print(f"Toplam {toplam_kayit} kayıt eklendi!")
print(f"Tarih aralığı: {baslangic} - {bugun}")

# Özet istatistikler
import sqlite3

conn = sqlite3.connect("lgs_takip.db")
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM soru_takip")
print(f"\nVeritabanındaki toplam kayıt: {c.fetchone()[0]}")

c.execute("""
    SELECT ders, COUNT(*) as sayi, SUM(soru_sayisi) as soru, 
           SUM(dogru) as dogru, SUM(yanlis) as yanlis
    FROM soru_takip GROUP BY ders ORDER BY ders
""")

print(f"\n{'Ders':<12} {'Kayıt':>6} {'Soru':>7} {'Doğru':>7} {'Yanlış':>7}")
print("-" * 45)
for row in c.fetchall():
    print(f"{row[0]:<12} {row[1]:>6} {row[2]:>7} {row[3]:>7} {row[4]:>7}")

conn.close()
print("\nTest verisi başarıyla oluşturuldu! Uygulamayı açabilirsiniz.")
