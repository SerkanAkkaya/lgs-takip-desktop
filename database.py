"""
LGS Hazırlık Takip - Veritabanı Katmanı
SQLite veritabanı işlemleri
"""

import os
import sys
import json
import re
import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta

# ─── Veritabanı Sürüm Yönetimi ───
# Her şema değişikliğinde DB_VERSION artırılır ve _migrations'a yeni fonksiyon eklenir.
DB_VERSION = 5


def _get_db_dir():
    """Veritabanı dosyasının konumunu belirle.
    
    PyInstaller ile paketlendiğinde: exe'nin bulunduğu dizin
    Normal çalıştırıldığında: script'in bulunduğu dizin
    
    Bu sayede exe yeniden oluşturulduğunda veriler korunur.
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller ile paketlenmiş exe
        return os.path.dirname(sys.executable)
    else:
        # Normal Python çalıştırma
        return os.path.dirname(os.path.abspath(__file__))


DB_PATH = os.path.join(_get_db_dir(), "lgs_takip.db")  # SQLite migration source / PDF folder anchor


def _get_database_url():
    """Get the per-machine Neon URL from the environment or adjacent dotenv file."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        return database_url

    app_dir = Path(_get_db_dir())
    for env_name in (".env.local", ".env"):
        env_path = app_dir / env_name
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == "DATABASE_URL":
                value = value.strip().strip('"').strip("'")
                if value:
                    return value
    raise RuntimeError(
        "Neon veritabanı bağlantısı bulunamadı. DATABASE_URL ortam değişkenini "
        "ayarlayın veya uygulamanın yanına .env.local dosyası koyun."
    )


class _Cursor:
    """Kept for backwards import compatibility; no longer used at runtime."""
    pass


DERSLER = ["Türkçe", "Matematik", "Fen", "Sosyal", "İngilizce", "Din"]

# LGS sınav ders bilgileri (soru sayıları sabit)
LGS_DERSLER = {
    "Türkçe":    {"soru_sayisi": 20, "katsayi": 4.0},
    "Matematik": {"soru_sayisi": 20, "katsayi": 4.0},
    "Fen":       {"soru_sayisi": 20, "katsayi": 4.0},
    "Sosyal":    {"soru_sayisi": 10, "katsayi": 4.0},
    "İngilizce": {"soru_sayisi": 10, "katsayi": 4.0},
    "Din":       {"soru_sayisi": 10, "katsayi": 4.0},
}

DERS_RENKLERI = {
    "Türkçe": "#E74C3C",
    "Matematik": "#3498DB",
    "Fen": "#2ECC71",
    "Sosyal": "#F39C12",
    "İngilizce": "#9B59B6",
    "Din": "#1ABC9C",
}


def _dict_row_factory(cursor, row):
    """Return each SQLite row as a plain dict so existing dict(row)/row[key] code works."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def get_connection():
    """Yerel SQLite veritabanı bağlantısı oluştur (yerel-öncelikli kullanım)."""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = _dict_row_factory
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA recursive_triggers = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    """Veritabanını oluştur, tabloları hazırla ve gerekirse migrate et."""
    conn = get_connection()
    cursor = conn.cursor()

    # ── Meta tablo (sürüm takibi) ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS db_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Mevcut sürümü oku
    cursor.execute("SELECT value FROM db_meta WHERE key = 'db_version'")
    row = cursor.fetchone()
    current_version = int(row["value"]) if row else 0

    # İlk kurulum: tabloları oluştur
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS soru_takip (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tarih TEXT NOT NULL,
            ders TEXT NOT NULL,
            soru_sayisi INTEGER NOT NULL DEFAULT 0,
            dogru INTEGER NOT NULL DEFAULT 0,
            yanlis INTEGER NOT NULL DEFAULT 0,
            net REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_tarih ON soru_takip(tarih)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_ders ON soru_takip(ders)
    """)

    # ── Sınav Takip Tabloları ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS kurumlar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kurum_adi TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sinavlar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sinav_adi TEXT NOT NULL,
            sinav_tarihi TEXT NOT NULL,
            kurum_id INTEGER,
            puan REAL,
            genel_derece INTEGER,
            il_derece INTEGER,
            ilce_derece INTEGER,
            kurum_derece INTEGER,
            sube_derece INTEGER,
            notlar TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (kurum_id) REFERENCES kurumlar(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sinav_dersleri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sinav_id INTEGER NOT NULL,
            ders TEXT NOT NULL,
            soru_sayisi INTEGER NOT NULL DEFAULT 0,
            dogru INTEGER NOT NULL DEFAULT 0,
            yanlis INTEGER NOT NULL DEFAULT 0,
            net REAL NOT NULL DEFAULT 0.0,
            FOREIGN KEY (sinav_id) REFERENCES sinavlar(id) ON DELETE CASCADE
        )
    """)

    # ── Ayarlar tablosu ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ayarlar (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # ── Karne (PDF) Takip Tabloları ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS karneler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dosya_adi TEXT NOT NULL,
            sinav_tarihi TEXT NOT NULL,
            kurum_adi TEXT,
            sinav_adi TEXT,
            raw_text TEXT,
            ai_ozet TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS karne_ders_analizi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            karne_id INTEGER NOT NULL,
            ders TEXT NOT NULL,
            soru_sayisi INTEGER DEFAULT 0,
            dogru INTEGER DEFAULT 0,
            yanlis INTEGER DEFAULT 0,
            bos INTEGER DEFAULT 0,
            net REAL DEFAULT 0.0,
            basari_yuzdesi REAL DEFAULT 0.0,
            FOREIGN KEY (karne_id) REFERENCES karneler(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS karne_konu_analizi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            karne_id INTEGER NOT NULL,
            ders TEXT NOT NULL,
            konu TEXT NOT NULL,
            kazanim TEXT,
            dogru INTEGER DEFAULT 0,
            yanlis INTEGER DEFAULT 0,
            bos INTEGER DEFAULT 0,
            toplam INTEGER DEFAULT 0,
            FOREIGN KEY (karne_id) REFERENCES karneler(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_karne_tarih ON karneler(sinav_tarihi)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_karne_konu_ders ON karne_konu_analizi(ders)
    """)

    # ── RAG (Bilgi Bankası) Tablosu ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            karne_id INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            embedding BLOB,
            provider TEXT NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (karne_id) REFERENCES karneler(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_rag_karne ON rag_chunks(karne_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_rag_provider ON rag_chunks(provider)
    """)

    # ── Migration'ları çalıştır ──
    _run_migrations(cursor, current_version)

    # ── Senkronizasyon şeması (uuid kolonları, outbox, trigger'lar) ──
    import sync
    sync.ensure_local_sync_schema(conn)

    # Sürümü güncelle
    cursor.execute("""
        INSERT OR REPLACE INTO db_meta (key, value)
        VALUES ('db_version', ?)
    """, (str(DB_VERSION),))

    conn.commit()
    conn.close()


def _run_migrations(cursor, current_version):
    """Sıralı migration'ları çalıştır.
    
    Her yeni şema değişikliği için:
    1. DB_VERSION'ı artır
    2. Aşağıya yeni migration fonksiyonu ekle
    3. migrations listesine ekle
    
    Örnek: Sürüm 2'de yeni bir kolon eklemek için:
        def _migrate_v2(cursor):
            cursor.execute("ALTER TABLE sinavlar ADD COLUMN yeni_alan TEXT")
    """
    # Migration fonksiyonları: index = sürüm numarası - 1
    migrations = [
        # v1: İlk sürüm, migration gerekmez (tablolar CREATE IF NOT EXISTS ile oluşturuluyor)
        lambda c: None,
        # v2: Ayarlar tablosu (CREATE IF NOT EXISTS ile oluşturuluyor, migration gerekmiyor)
        lambda c: None,
        # v3: Karne tabloları (CREATE IF NOT EXISTS ile oluşturuluyor, migration gerekmiyor)
        lambda c: None,
        # v4: RAG chunks tablosu (CREATE IF NOT EXISTS ile oluşturuluyor)
        lambda c: None,
        # v5: SQLite ile uyumlu JSON çıktısı için zaman damgalarını metin yap.
        _migrate_v5,
    ]

    for version_num in range(current_version, DB_VERSION):
        if version_num < len(migrations):
            migrations[version_num](cursor)


def _migrate_v5(cursor):
    # Yerel SQLite'ta created_at zaten TEXT; Postgres'e özel ALTER adımları gerekmez.
    return None


# ═══════════════════════════════════════════════════════════
# EXPORT / IMPORT (Yedekleme & Geri Yükleme)
# ═══════════════════════════════════════════════════════════

def export_data(dosya_yolu: str) -> dict:
    """Tüm verileri JSON dosyasına export et.
    
    Returns: İstatistik bilgileri (tablo bazında kayıt sayıları)
    """
    conn = get_connection()
    cursor = conn.cursor()

    data = {
        "meta": {
            "app": "LGS Hazırlık Takip",
            "db_version": DB_VERSION,
            "export_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "soru_takip": [],
        "kurumlar": [],
        "sinavlar": [],
        "sinav_dersleri": [],
    }

    # soru_takip
    cursor.execute("SELECT * FROM soru_takip ORDER BY id")
    for row in cursor.fetchall():
        r = dict(row)
        data["soru_takip"].append(r)

    # kurumlar
    cursor.execute("SELECT * FROM kurumlar ORDER BY id")
    for row in cursor.fetchall():
        data["kurumlar"].append(dict(row))

    # sinavlar
    cursor.execute("SELECT * FROM sinavlar ORDER BY id")
    for row in cursor.fetchall():
        data["sinavlar"].append(dict(row))

    # sinav_dersleri
    cursor.execute("SELECT * FROM sinav_dersleri ORDER BY id")
    for row in cursor.fetchall():
        data["sinav_dersleri"].append(dict(row))

    conn.close()

    with open(dosya_yolu, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    stats = {
        "soru_takip": len(data["soru_takip"]),
        "kurumlar": len(data["kurumlar"]),
        "sinavlar": len(data["sinavlar"]),
        "sinav_dersleri": len(data["sinav_dersleri"]),
    }
    return stats


def import_data(dosya_yolu: str, mod="ekle") -> dict:
    """JSON dosyasından veri import et.
    
    mod:
        'ekle': Mevcut verilerin üzerine ekler (ID'ler yeniden atanır)
        'sifirla': Mevcut tüm verileri siler ve import eder
    
    Returns: İstatistik bilgileri
    """
    with open(dosya_yolu, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Versiyon kontrolü
    file_version = data.get("meta", {}).get("db_version", 0)
    if file_version > DB_VERSION:
        raise ValueError(
            f"Bu dosya daha yeni bir sürümle oluşturulmuş (v{file_version}). "
            f"Lütfen uygulamayı güncelleyin (mevcut: v{DB_VERSION})."
        )

    conn = get_connection()
    cursor = conn.cursor()

    stats = {"soru_takip": 0, "kurumlar": 0, "sinavlar": 0, "sinav_dersleri": 0}

    try:
        if mod == "sifirla":
            cursor.execute("DELETE FROM sinav_dersleri")
            cursor.execute("DELETE FROM sinavlar")
            cursor.execute("DELETE FROM kurumlar")
            cursor.execute("DELETE FROM soru_takip")

        # ── Kurum ID eşleme (eski ID → yeni ID) ──
        kurum_id_map = {}
        for k in data.get("kurumlar", []):
            eski_id = k["id"]
            # Aynı isimde kurum var mı?
            cursor.execute("SELECT id FROM kurumlar WHERE kurum_adi = ?", (k["kurum_adi"],))
            existing = cursor.fetchone()
            if existing:
                kurum_id_map[eski_id] = existing["id"]
            else:
                cursor.execute(
                    "INSERT INTO kurumlar (kurum_adi, created_at) VALUES (?, ?)",
                    (k["kurum_adi"], k.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                )
                kurum_id_map[eski_id] = cursor.lastrowid
                stats["kurumlar"] += 1

        # ── Soru takip ──
        for r in data.get("soru_takip", []):
            cursor.execute(
                "INSERT INTO soru_takip (tarih, ders, soru_sayisi, dogru, yanlis, net, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (r["tarih"], r["ders"], r["soru_sayisi"], r["dogru"], r["yanlis"],
                 r["net"], r.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            )
            stats["soru_takip"] += 1

        # ── Sınavlar (ID eşlemeli) ──
        sinav_id_map = {}
        for s in data.get("sinavlar", []):
            eski_id = s["id"]
            yeni_kurum_id = kurum_id_map.get(s.get("kurum_id")) if s.get("kurum_id") else None
            cursor.execute(
                "INSERT INTO sinavlar (sinav_adi, sinav_tarihi, kurum_id, puan, "
                "genel_derece, il_derece, ilce_derece, kurum_derece, sube_derece, notlar, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (s["sinav_adi"], s["sinav_tarihi"], yeni_kurum_id, s.get("puan"),
                 s.get("genel_derece"), s.get("il_derece"), s.get("ilce_derece"),
                 s.get("kurum_derece"), s.get("sube_derece"), s.get("notlar"),
                 s.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            )
            sinav_id_map[eski_id] = cursor.lastrowid
            stats["sinavlar"] += 1

        # ── Sınav dersleri (ID eşlemeli) ──
        for sd in data.get("sinav_dersleri", []):
            yeni_sinav_id = sinav_id_map.get(sd["sinav_id"])
            if yeni_sinav_id:
                cursor.execute(
                    "INSERT INTO sinav_dersleri (sinav_id, ders, soru_sayisi, dogru, yanlis, net) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (yeni_sinav_id, sd["ders"], sd["soru_sayisi"], sd["dogru"],
                     sd["yanlis"], sd["net"])
                )
                stats["sinav_dersleri"] += 1

        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    
    conn.close()
    return stats


def kayit_ekle(tarih: str, ders: str, soru_sayisi: int, dogru: int, yanlis: int) -> int:
    """Yeni kayıt ekle. Net hesaplaması otomatik yapılır."""
    net = dogru - (yanlis / 4.0)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO soru_takip (tarih, ders, soru_sayisi, dogru, yanlis, net)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (tarih, ders, soru_sayisi, dogru, yanlis, round(net, 2)),
    )
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    return last_id


def kayit_sil(kayit_id: int):
    """Kayıt sil."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM soru_takip WHERE id = ?", (kayit_id,))
    conn.commit()
    conn.close()


def kayit_guncelle(kayit_id: int, tarih: str, ders: str, soru_sayisi: int, dogru: int, yanlis: int):
    """Kayıt güncelle."""
    net = dogru - (yanlis / 4.0)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE soru_takip 
        SET tarih=?, ders=?, soru_sayisi=?, dogru=?, yanlis=?, net=?
        WHERE id=?
    """,
        (tarih, ders, soru_sayisi, dogru, yanlis, round(net, 2), kayit_id),
    )
    conn.commit()
    conn.close()


def tum_kayitlari_getir(tarih_baslangic=None, tarih_bitis=None, ders=None):
    """Kayıtları filtrele ve getir."""
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM soru_takip WHERE 1=1"
    params = []

    if tarih_baslangic:
        query += " AND tarih >= ?"
        params.append(tarih_baslangic)
    if tarih_bitis:
        query += " AND tarih <= ?"
        params.append(tarih_bitis)
    if ders and ders != "Tümü":
        query += " AND ders = ?"
        params.append(ders)

    query += " ORDER BY tarih DESC, ders"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def gunluk_ozet(tarih_baslangic=None, tarih_bitis=None):
    """Günlük özet istatistikleri."""
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT tarih, ders,
               SUM(soru_sayisi) as toplam_soru,
               SUM(dogru) as toplam_dogru,
               SUM(yanlis) as toplam_yanlis,
               SUM(net) as toplam_net
        FROM soru_takip
        WHERE 1=1
    """
    params = []
    if tarih_baslangic:
        query += " AND tarih >= ?"
        params.append(tarih_baslangic)
    if tarih_bitis:
        query += " AND tarih <= ?"
        params.append(tarih_bitis)

    query += " GROUP BY tarih, ders ORDER BY tarih, ders"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def ders_bazinda_toplam(tarih_baslangic=None, tarih_bitis=None):
    """Ders bazında toplam istatistikler."""
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT ders,
               SUM(soru_sayisi) as toplam_soru,
               SUM(dogru) as toplam_dogru,
               SUM(yanlis) as toplam_yanlis,
               SUM(net) as toplam_net,
               COUNT(*) as kayit_sayisi
        FROM soru_takip
        WHERE 1=1
    """
    params = []
    if tarih_baslangic:
        query += " AND tarih >= ?"
        params.append(tarih_baslangic)
    if tarih_bitis:
        query += " AND tarih <= ?"
        params.append(tarih_bitis)

    query += " GROUP BY ders ORDER BY ders"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def aylik_ozet(yil=None):
    """Aylık özet (ders bazında)."""
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT strftime('%Y-%m', tarih) as ay,
               ders,
               SUM(soru_sayisi) as toplam_soru,
               SUM(dogru) as toplam_dogru,
               SUM(yanlis) as toplam_yanlis,
               SUM(net) as toplam_net
        FROM soru_takip
        WHERE 1=1
    """
    params = []
    if yil:
        query += " AND strftime('%Y', tarih) = ?"
        params.append(str(yil))

    query += " GROUP BY ay, ders ORDER BY ay, ders"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ═══════════════════════════════════════════════════════════
# AYARLAR İŞLEMLERİ
# ═══════════════════════════════════════════════════════════

def kaydet_ayar(key: str, value: str):
    """Ayar kaydet veya güncelle."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO ayarlar (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def oku_ayar(key: str, varsayilan: str = "") -> str:
    """Ayar oku."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM ayarlar WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else varsayilan


def ai_analiz_verisi(son_gun: int = 90) -> dict:
    """AI analizi için kapsamlı veri paketi hazırla.
    
    Sadece özet istatistikler gönderilir, kişisel bilgi gönderilmez.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    veri = {"son_gun": son_gun, "dersler": {}, "sinavlar": [], "genel": {}}
    
    # ── Ders bazında günlük istatistikler ──
    for ders in DERSLER:
        cursor.execute("""
            SELECT tarih,
                   SUM(soru_sayisi) as soru,
                   SUM(dogru) as dogru,
                   SUM(yanlis) as yanlis,
                   SUM(net) as net
            FROM soru_takip
            WHERE ders = ? AND tarih >= date('now', '-' || ? || ' days', 'localtime')
            GROUP BY tarih
            ORDER BY tarih
        """, (ders, son_gun))
        rows = cursor.fetchall()
        if rows:
            toplam_soru = sum(r["soru"] for r in rows)
            toplam_dogru = sum(r["dogru"] for r in rows)
            toplam_yanlis = sum(r["yanlis"] for r in rows)
            toplam_net = sum(r["net"] for r in rows)
            gun_sayisi = len(rows)
            basari = (toplam_dogru / toplam_soru * 100) if toplam_soru > 0 else 0
            
            # Son 7 gün vs önceki 7 gün karşılaştırma
            son7 = [r for r in rows if r["tarih"] >= (date.today() - timedelta(days=7)).strftime('%Y-%m-%d')]
            onceki7 = [r for r in rows if r["tarih"] < (date.today() - timedelta(days=7)).strftime('%Y-%m-%d')
                       and r["tarih"] >= (date.today() - timedelta(days=14)).strftime('%Y-%m-%d')]
            
            son7_basari = 0
            onceki7_basari = 0
            if son7:
                s7_soru = sum(r["soru"] for r in son7)
                s7_dogru = sum(r["dogru"] for r in son7)
                son7_basari = (s7_dogru / s7_soru * 100) if s7_soru > 0 else 0
            if onceki7:
                o7_soru = sum(r["soru"] for r in onceki7)
                o7_dogru = sum(r["dogru"] for r in onceki7)
                onceki7_basari = (o7_dogru / o7_soru * 100) if o7_soru > 0 else 0
            
            veri["dersler"][ders] = {
                "toplam_soru": toplam_soru,
                "toplam_dogru": toplam_dogru,
                "toplam_yanlis": toplam_yanlis,
                "toplam_net": round(toplam_net, 2),
                "gun_sayisi": gun_sayisi,
                "basari_yuzdesi": round(basari, 1),
                "gunluk_ort_soru": round(toplam_soru / gun_sayisi, 1),
                "son7_basari": round(son7_basari, 1),
                "onceki7_basari": round(onceki7_basari, 1),
            }
    
    # ── Genel istatistik ──
    cursor.execute("""
        SELECT COUNT(DISTINCT tarih) as toplam_gun,
               SUM(soru_sayisi) as toplam_soru,
               SUM(dogru) as toplam_dogru,
               SUM(yanlis) as toplam_yanlis,
               SUM(net) as toplam_net
        FROM soru_takip
        WHERE tarih >= date('now', '-' || ? || ' days', 'localtime')
    """, (son_gun,))
    genel = cursor.fetchone()
    if genel and genel["toplam_soru"]:
        veri["genel"] = {
            "toplam_gun": genel["toplam_gun"],
            "toplam_soru": genel["toplam_soru"],
            "toplam_dogru": genel["toplam_dogru"],
            "toplam_yanlis": genel["toplam_yanlis"],
            "toplam_net": round(genel["toplam_net"], 2),
            "genel_basari": round(genel["toplam_dogru"] / genel["toplam_soru"] * 100, 1),
        }
    
    # ── Sınav sonuçları (son 5) ──
    cursor.execute("""
        SELECT s.sinav_adi, s.sinav_tarihi, s.puan,
               s.genel_derece, s.il_derece, k.kurum_adi
        FROM sinavlar s
        LEFT JOIN kurumlar k ON s.kurum_id = k.id
        ORDER BY s.sinav_tarihi DESC
        LIMIT 5
    """) 
    for row in cursor.fetchall():
        sinav = dict(row)
        # Ders detayları
        cursor.execute("""
            SELECT ders, soru_sayisi, dogru, yanlis, net
            FROM sinav_dersleri WHERE sinav_id = (
                SELECT id FROM sinavlar WHERE sinav_adi = ? AND sinav_tarihi = ? LIMIT 1
            )
        """, (sinav["sinav_adi"], sinav["sinav_tarihi"]))
        sinav["dersler"] = [dict(d) for d in cursor.fetchall()]
        veri["sinavlar"].append(sinav)
    
    conn.close()
    return veri


def trend_verisi(ders=None, son_gun=30):
    """Trend analizi için veri. Son N gün."""
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT tarih, ders,
               SUM(soru_sayisi) as toplam_soru,
               SUM(dogru) as toplam_dogru,
               SUM(yanlis) as toplam_yanlis,
               SUM(net) as toplam_net
        FROM soru_takip
        WHERE tarih >= date('now', '-' || ? || ' days', 'localtime')
    """
    params = [son_gun]

    if ders and ders != "Tümü":
        query += " AND ders = ?"
        params.append(ders)

    query += " GROUP BY tarih, ders ORDER BY tarih, ders"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ═══════════════════════════════════════════════════════════
# KURUM İŞLEMLERİ
# ═══════════════════════════════════════════════════════════

def kurum_ekle(kurum_adi: str) -> int:
    """Yeni kurum ekle."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO kurumlar (kurum_adi) VALUES (?)", (kurum_adi.strip(),))
        conn.commit()
        last_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        last_id = -1  # Zaten var
    conn.close()
    return last_id


def kurum_sil(kurum_id: int):
    """Kurum sil."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE sinavlar SET kurum_id = NULL WHERE kurum_id = ?", (kurum_id,))
    cursor.execute("DELETE FROM kurumlar WHERE id = ?", (kurum_id,))
    conn.commit()
    conn.close()


def kurum_guncelle(kurum_id: int, kurum_adi: str):
    """Kurum adını güncelle."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE kurumlar SET kurum_adi = ? WHERE id = ?", (kurum_adi.strip(), kurum_id))
    conn.commit()
    conn.close()


def kurumlari_getir():
    """Tüm kurumları getir."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM kurumlar ORDER BY kurum_adi")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ═══════════════════════════════════════════════════════════
# SINAV İŞLEMLERİ
# ═══════════════════════════════════════════════════════════

def sinav_ekle(sinav_adi: str, sinav_tarihi: str, kurum_id=None,
               puan=None, genel_derece=None, il_derece=None,
               ilce_derece=None, kurum_derece=None, sube_derece=None,
               notlar=None) -> int:
    """Yeni sınav kaydı ekle."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sinavlar (sinav_adi, sinav_tarihi, kurum_id, puan,
            genel_derece, il_derece, ilce_derece, kurum_derece, sube_derece, notlar)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (sinav_adi, sinav_tarihi, kurum_id, puan,
          genel_derece, il_derece, ilce_derece, kurum_derece, sube_derece, notlar))
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    return last_id


def sinav_guncelle(sinav_id: int, sinav_adi: str, sinav_tarihi: str, kurum_id=None,
                   puan=None, genel_derece=None, il_derece=None,
                   ilce_derece=None, kurum_derece=None, sube_derece=None,
                   notlar=None):
    """Sınav kaydını güncelle."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE sinavlar SET sinav_adi=?, sinav_tarihi=?, kurum_id=?, puan=?,
            genel_derece=?, il_derece=?, ilce_derece=?, kurum_derece=?, sube_derece=?, notlar=?
        WHERE id=?
    """, (sinav_adi, sinav_tarihi, kurum_id, puan,
          genel_derece, il_derece, ilce_derece, kurum_derece, sube_derece, notlar, sinav_id))
    conn.commit()
    conn.close()


def sinav_sil(sinav_id: int):
    """Sınavı ve ders kayıtlarını sil."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sinav_dersleri WHERE sinav_id = ?", (sinav_id,))
    cursor.execute("DELETE FROM sinavlar WHERE id = ?", (sinav_id,))
    conn.commit()
    conn.close()


def sinav_ders_ekle(sinav_id: int, ders: str, soru_sayisi: int, dogru: int, yanlis: int) -> int:
    """Sınava ders sonucu ekle. LGS'de 3 yanlış 1 doğruyu götürür."""
    net = dogru - (yanlis / 3.0)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sinav_dersleri (sinav_id, ders, soru_sayisi, dogru, yanlis, net)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (sinav_id, ders, soru_sayisi, dogru, yanlis, round(net, 2)))
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    return last_id


def sinav_dersleri_sil(sinav_id: int):
    """Sınavın ders kayıtlarını sil (güncelleme için)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sinav_dersleri WHERE sinav_id = ?", (sinav_id,))
    conn.commit()
    conn.close()


def sinavlari_getir(kurum_id=None, tarih_baslangic=None, tarih_bitis=None):
    """Sınavları filtrele ve getir."""
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT s.*, k.kurum_adi
        FROM sinavlar s
        LEFT JOIN kurumlar k ON s.kurum_id = k.id
        WHERE 1=1
    """
    params = []
    if kurum_id:
        query += " AND s.kurum_id = ?"
        params.append(kurum_id)
    if tarih_baslangic:
        query += " AND s.sinav_tarihi >= ?"
        params.append(tarih_baslangic)
    if tarih_bitis:
        query += " AND s.sinav_tarihi <= ?"
        params.append(tarih_bitis)
    query += " ORDER BY s.sinav_tarihi DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def sinav_detay_getir(sinav_id: int):
    """Sınav detayını ders bilgileriyle getir."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT s.*, k.kurum_adi
        FROM sinavlar s
        LEFT JOIN kurumlar k ON s.kurum_id = k.id
        WHERE s.id = ?
    """, (sinav_id,))
    sinav = cursor.fetchone()

    cursor.execute("""
        SELECT * FROM sinav_dersleri
        WHERE sinav_id = ?
        ORDER BY ders
    """, (sinav_id,))
    dersler = cursor.fetchall()

    conn.close()
    if sinav:
        return {"sinav": dict(sinav), "dersler": [dict(d) for d in dersler]}
    return None


def sinav_karsilastir(kurum_id=None):
    """Sınavları karşılaştırma için getir (tarih sıralı, ders detaylarıyla)."""
    conn = get_connection()
    cursor = conn.cursor()

    query = """
        SELECT s.id, s.sinav_adi, s.sinav_tarihi, s.puan,
               s.genel_derece, s.il_derece, s.ilce_derece,
               s.kurum_derece, s.sube_derece,
               k.kurum_adi,
               sd.ders, sd.soru_sayisi, sd.dogru, sd.yanlis, sd.net
        FROM sinavlar s
        LEFT JOIN kurumlar k ON s.kurum_id = k.id
        LEFT JOIN sinav_dersleri sd ON s.id = sd.sinav_id
        WHERE 1=1
    """
    params = []
    if kurum_id:
        query += " AND s.kurum_id = ?"
        params.append(kurum_id)

    query += " ORDER BY s.sinav_tarihi ASC, s.id, sd.ders"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ═══════════════════════════════════════════════════════════
# KARNE (PDF) İŞLEMLERİ
# ═══════════════════════════════════════════════════════════

def karne_ekle(dosya_adi: str, sinav_tarihi: str, kurum_adi: str = "",
               sinav_adi: str = "", raw_text: str = "", ai_ozet: str = "") -> int:
    """Yeni karne kaydı ekle."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO karneler (dosya_adi, sinav_tarihi, kurum_adi, sinav_adi, raw_text, ai_ozet)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (dosya_adi, sinav_tarihi, kurum_adi, sinav_adi, raw_text, ai_ozet))
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    return last_id


def karne_ders_ekle(karne_id: int, ders: str, soru_sayisi: int = 0,
                    dogru: int = 0, yanlis: int = 0, bos: int = 0,
                    net: float = 0.0, basari_yuzdesi: float = 0.0) -> int:
    """Karneye ders analizi ekle."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO karne_ders_analizi (karne_id, ders, soru_sayisi, dogru, yanlis, bos, net, basari_yuzdesi)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (karne_id, ders, soru_sayisi, dogru, yanlis, bos, round(net, 2), round(basari_yuzdesi, 1)))
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    return last_id


def karne_konu_ekle(karne_id: int, ders: str, konu: str, kazanim: str = "",
                    dogru: int = 0, yanlis: int = 0, bos: int = 0, toplam: int = 0) -> int:
    """Karneye konu analizi ekle."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO karne_konu_analizi (karne_id, ders, konu, kazanim, dogru, yanlis, bos, toplam)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (karne_id, ders, konu, kazanim, dogru, yanlis, bos, toplam))
    conn.commit()
    last_id = cursor.lastrowid
    conn.close()
    return last_id


def karne_sil(karne_id: int):
    """Karne ve tüm alt kayıtlarını sil."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rag_chunks WHERE karne_id = ?", (karne_id,))
    cursor.execute("DELETE FROM karne_konu_analizi WHERE karne_id = ?", (karne_id,))
    cursor.execute("DELETE FROM karne_ders_analizi WHERE karne_id = ?", (karne_id,))
    cursor.execute("DELETE FROM karneler WHERE id = ?", (karne_id,))
    conn.commit()
    conn.close()


def karneleri_getir(son_gun: int = None):
    """Karneleri getir. son_gun verilirse filtrele."""
    conn = get_connection()
    cursor = conn.cursor()
    if son_gun:
        cursor.execute("""
            SELECT * FROM karneler
            WHERE sinav_tarihi >= date('now', '-' || ? || ' days', 'localtime')
            ORDER BY sinav_tarihi DESC
        """, (son_gun,))
    else:
        cursor.execute("SELECT * FROM karneler ORDER BY sinav_tarihi DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def karne_detay_getir(karne_id: int):
    """Karne detayını ders ve konu bilgileriyle getir."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM karneler WHERE id = ?", (karne_id,))
    karne = cursor.fetchone()

    cursor.execute("SELECT * FROM karne_ders_analizi WHERE karne_id = ? ORDER BY ders", (karne_id,))
    dersler = cursor.fetchall()

    cursor.execute("SELECT * FROM karne_konu_analizi WHERE karne_id = ? ORDER BY ders, konu", (karne_id,))
    konular = cursor.fetchall()

    conn.close()
    if karne:
        return {
            "karne": dict(karne),
            "dersler": [dict(d) for d in dersler],
            "konular": [dict(k) for k in konular],
        }
    return None


def karne_konu_raporu(son_gun: int = None, ders: str = None):
    """Konu bazlı hata raporu — tüm karneler üzerinden toplu analiz.
    
    Returns: [{ders, konu, kazanim, toplam_dogru, toplam_yanlis, toplam_bos,
               toplam_soru, hata_orani, karne_sayisi}]
    """
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT kka.ders, kka.konu, kka.kazanim,
               SUM(kka.dogru) as toplam_dogru,
               SUM(kka.yanlis) as toplam_yanlis,
               SUM(kka.bos) as toplam_bos,
               SUM(kka.toplam) as toplam_soru,
               COUNT(DISTINCT kka.karne_id) as karne_sayisi
        FROM karne_konu_analizi kka
        JOIN karneler k ON kka.karne_id = k.id
        WHERE 1=1
    """
    params = []
    if son_gun:
        query += " AND k.sinav_tarihi >= date('now', '-' || ? || ' days', 'localtime')"
        params.append(son_gun)
    if ders and ders != "Tümü":
        query += " AND kka.ders = ?"
        params.append(ders)

    query += " GROUP BY kka.ders, kka.konu, kka.kazanim ORDER BY kka.ders, SUM(kka.yanlis) DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        toplam = d["toplam_soru"] or 1
        d["hata_orani"] = round((d["toplam_yanlis"] + d["toplam_bos"]) / toplam * 100, 1)
        result.append(d)
    return result


def karne_gelisim_raporu(ders: str = None):
    """Karne bazlı gelişim raporu — tarih sıralı ders başarı oranları.
    
    Returns: [{sinav_tarihi, sinav_adi, kurum_adi, ders, soru_sayisi, dogru, yanlis, bos, net, basari}]
    """
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT k.sinav_tarihi, k.sinav_adi, k.kurum_adi,
               kda.ders, kda.soru_sayisi, kda.dogru, kda.yanlis, kda.bos,
               kda.net, kda.basari_yuzdesi as basari
        FROM karne_ders_analizi kda
        JOIN karneler k ON kda.karne_id = k.id
        WHERE 1=1
    """
    params = []
    if ders and ders != "Tümü":
        query += " AND kda.ders = ?"
        params.append(ders)
    query += " ORDER BY k.sinav_tarihi ASC, kda.ders"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ═══════════════════════════════════════════════════════════
# RAG (BİLGİ BANKASI) İŞLEMLERİ
# ═══════════════════════════════════════════════════════════

def rag_chunks_toplu_ekle(karne_id: int, chunks: list, embeddings_bytes: list,
                          provider: str):
    """RAG bilgi bankasına toplu chunk ekle."""
    conn = get_connection()
    cursor = conn.cursor()
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings_bytes)):
        cursor.execute("""
            INSERT INTO rag_chunks (karne_id, chunk_text, embedding, provider, chunk_index)
            VALUES (?, ?, ?, ?, ?)
        """, (karne_id, chunk, emb, provider, i))
    conn.commit()
    conn.close()


def rag_tum_chunklar(provider: str = None):
    """Tüm RAG chunk'larını getir. provider filtresi opsiyonel."""
    conn = get_connection()
    cursor = conn.cursor()
    if provider:
        cursor.execute("""
            SELECT rc.*, k.dosya_adi, k.sinav_adi, k.sinav_tarihi
            FROM rag_chunks rc
            JOIN karneler k ON rc.karne_id = k.id
            WHERE rc.provider = ?
            ORDER BY rc.karne_id, rc.chunk_index
        """, (provider,))
    else:
        cursor.execute("""
            SELECT rc.*, k.dosya_adi, k.sinav_adi, k.sinav_tarihi
            FROM rag_chunks rc
            JOIN karneler k ON rc.karne_id = k.id
            ORDER BY rc.karne_id, rc.chunk_index
        """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def rag_karne_chunklari_sil(karne_id: int):
    """Belirli bir karneye ait RAG chunk'larını sil."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rag_chunks WHERE karne_id = ?", (karne_id,))
    conn.commit()
    conn.close()


def rag_chunk_sayisi(provider: str = None) -> dict:
    """RAG bilgi bankası istatistikleri."""
    conn = get_connection()
    cursor = conn.cursor()
    if provider:
        cursor.execute("""
            SELECT COUNT(*) as chunk_sayisi,
                   COUNT(DISTINCT karne_id) as karne_sayisi
            FROM rag_chunks WHERE provider = ?
        """, (provider,))
    else:
        cursor.execute("""
            SELECT COUNT(*) as chunk_sayisi,
                   COUNT(DISTINCT karne_id) as karne_sayisi
            FROM rag_chunks
        """)
    row = cursor.fetchone()
    conn.close()
    return {"chunk_sayisi": row["chunk_sayisi"], "karne_sayisi": row["karne_sayisi"]}


def rag_tum_raw_text():
    """Tüm karnelerin raw_text'lerini getir (re-embedding için)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, dosya_adi, raw_text FROM karneler WHERE raw_text IS NOT NULL AND raw_text != ''")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def rag_provider_temizle(provider: str):
    """Belirli provider'a ait tüm chunk'ları sil (provider değişiminde)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rag_chunks WHERE provider = ?", (provider,))
    conn.commit()
    conn.close()
