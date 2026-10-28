"""
Tek seferlik Neon migration: "Sosyal" dersini "İnkılap" olarak yeniden adlandır.

Yerel SQLite tarafı uygulama açılışında otomatik (database._migrate_v6) güncellenir.
Bu script aynı değişikliği ortak Neon veritabanında uygular. İdempotenttir:
ikinci kez çalıştırıldığında 0 satır günceller.

Kullanım:
    python migrate_sosyal_to_inkilap.py            # dry-run (sayıları gösterir)
    python migrate_sosyal_to_inkilap.py --apply    # Neon'da uygula
"""

import argparse

import sync

TABLES = ("soru_takip", "sinav_dersleri", "karne_ders_analizi", "karne_konu_analizi")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Neon'da gerçekten uygula")
    args = ap.parse_args()

    try:
        remote = sync.get_remote_connection()
    except Exception as exc:
        print(f"Neon bağlantısı kurulamadı: {type(exc).__name__}: {exc}")
        print("İşlem yapılamadı. Bağlantıyı kontrol edip tekrar deneyin.")
        return

    try:
        print("=" * 56)
        print("Neon: 'Sosyal' -> 'İnkılap' ders yeniden adlandırma")
        print("=" * 56)
        toplam = 0
        for t in TABLES:
            n = remote.execute(
                f"SELECT COUNT(*) AS n FROM {t} WHERE ders = 'Sosyal'"
            ).fetchone()["n"]
            print(f"  {t}: 'Sosyal' = {n}")
            toplam += n
        print(f"  Toplam güncellenecek satır: {toplam}")

        if not args.apply:
            print("\nDRY-RUN: hiçbir değişiklik yapılmadı. Uygulamak için --apply ekleyin.")
            return

        guncellenen = 0
        for t in TABLES:
            cur = remote.execute(
                f"UPDATE {t} SET ders = 'İnkılap' WHERE ders = 'Sosyal'"
            )
            guncellenen += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        remote.commit()
        print(f"\nUygulandı. Güncellenen satır: {guncellenen}")

        # Doğrulama
        kalan = sum(
            remote.execute(f"SELECT COUNT(*) AS n FROM {t} WHERE ders = 'Sosyal'").fetchone()["n"]
            for t in TABLES
        )
        print(f"Kalan 'Sosyal' satırı: {kalan} (0 olmalı)")
    finally:
        remote.close()


if __name__ == "__main__":
    main()
