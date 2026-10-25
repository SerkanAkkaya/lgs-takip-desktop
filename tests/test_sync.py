"""
Senkronizasyon katmanı için otomatik testler.

Kapsam (gerçek Neon GEREKTİRMEZ — yerel SQLite üzerinde çalışır):
  * Her kullanıcı verisi tablosu için ekleme/güncelleme/silme outbox olayı üretir.
  * executemany (import_data) ve cascade/çoklu silmeler de yakalanır.
  * uuid ataması + benzersizlik; taşınmış kayıtlar için deterministik uuid.
  * Gelen değişikliklerin yerele uygulanması (pull mantığı): idempotency, tombstone,
    foreign key sırası, ebeveyn gelmeden çocuğun ertelenmesi.
  * Senkronizasyon sırasında gelen kayıtlar yeni outbox olayı üretmez (döngü önleme).
  * Çevrimdışı: internet olmadan CRUD çalışır; bekleyen olaylar kaybolmaz.
  * Hassas ayarların senkronize edilmemesi.
  * push() yerel defter tutması: sahte remote ile idempotent 'done' işaretleme.

Gerçek Neon round-trip ve 3 bilgisayarlı senaryo burada test EDİLEMEZ (Postgres gerekir).
"""

import importlib
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import sync


@pytest.fixture()
def db(tmp_path):
    """Her test için temiz bir yerel SQLite veritabanı."""
    path = str(tmp_path / "test_lgs.db")
    old = database.DB_PATH
    database.DB_PATH = path
    database.init_db()
    yield path
    database.DB_PATH = old


def _queue(conn):
    return conn.execute(
        "SELECT tbl, op, row_uuid FROM sync_queue ORDER BY seq"
    ).fetchall()


# ─────────────────────────────────────────────────────────────
# 1) Outbox: her tabloda ekleme/güncelleme/silme olay üretir
# ─────────────────────────────────────────────────────────────

def test_insert_update_delete_soru_takip_outbox(db):
    rid = database.kayit_ekle("2025-01-01", "Matematik", 20, 15, 3)
    database.kayit_guncelle(rid, "2025-01-01", "Matematik", 20, 18, 2)
    database.kayit_sil(rid)
    conn = database.get_connection()
    ops = [(r["tbl"], r["op"]) for r in _queue(conn)]
    conn.close()
    assert ("soru_takip", "I") in ops
    assert ("soru_takip", "U") in ops
    assert ("soru_takip", "D") in ops


def test_all_user_tables_insert_outbox(db):
    kid = database.kurum_ekle("Kurum A")
    sid = database.sinav_ekle("Deneme", "2025-01-02", kid, puan=440.0)
    database.sinav_ders_ekle(sid, "Fen", 20, 12, 6)
    karne_id = database.karne_ekle("k.pdf", "2025-01-03", "Kurum A", "Deneme")
    database.karne_ders_ekle(karne_id, "Fen", 20, 12, 6, 2)
    database.karne_konu_ekle(karne_id, "Fen", "Kuvvet", "Kazanım-1", 3, 1, 0, 4)
    database.rag_chunks_toplu_ekle(karne_id, ["metin"], [b"\x00\x01\x02\x03"], "gemini")

    conn = database.get_connection()
    tables = {r["tbl"] for r in _queue(conn) if r["op"] == "I"}
    conn.close()
    for t in ("kurumlar", "sinavlar", "sinav_dersleri", "karneler",
              "karne_ders_analizi", "karne_konu_analizi", "rag_chunks"):
        assert t in tables, f"{t} için ekleme olayı üretilmedi"


def test_cascade_delete_emits_child_tombstones(db):
    karne_id = database.karne_ekle("k.pdf", "2025-01-03")
    database.karne_ders_ekle(karne_id, "Fen", 20, 12, 6, 2)
    database.karne_konu_ekle(karne_id, "Fen", "Kuvvet", "", 3, 1, 0, 4)
    database.rag_chunks_toplu_ekle(karne_id, ["m"], [b"\x00"], "gemini")

    database.karne_sil(karne_id)  # alt kayıtları da elle siler

    conn = database.get_connection()
    deletes = {r["tbl"] for r in _queue(conn) if r["op"] == "D"}
    tomb = {r["tbl"] for r in conn.execute(
        "SELECT tbl FROM sync_tombstones").fetchall()}
    conn.close()
    for t in ("karneler", "karne_ders_analizi", "karne_konu_analizi", "rag_chunks"):
        assert t in deletes, f"{t} silme olayı yok"
        assert t in tomb, f"{t} tombstone yok"


def test_executemany_import_is_captured(db):
    # import_data çoklu INSERT yapar; trigger'lar yine de olay üretmeli.
    import json
    data = {
        "meta": {"db_version": database.DB_VERSION},
        "kurumlar": [{"id": 1, "kurum_adi": "Imp Kurum", "created_at": "2025-01-01 00:00:00"}],
        "soru_takip": [{"id": 1, "tarih": "2025-01-01", "ders": "Türkçe",
                        "soru_sayisi": 10, "dogru": 8, "yanlis": 2, "net": 7.5,
                        "created_at": "2025-01-01 00:00:00"}],
        "sinavlar": [], "sinav_dersleri": [],
    }
    p = os.path.join(os.path.dirname(database.DB_PATH), "imp.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)
    database.import_data(p, mod="ekle")
    conn = database.get_connection()
    tables = {r["tbl"] for r in _queue(conn) if r["op"] == "I"}
    conn.close()
    assert "kurumlar" in tables
    assert "soru_takip" in tables


# ─────────────────────────────────────────────────────────────
# 2) uuid ataması ve benzersizlik
# ─────────────────────────────────────────────────────────────

def test_uuid_assigned_and_unique(db):
    ids = [database.kayit_ekle("2025-01-01", "Matematik", 20, 15, 3) for _ in range(5)]
    conn = database.get_connection()
    uuids = [conn.execute("SELECT uuid FROM soru_takip WHERE id=?", (i,)).fetchone()["uuid"]
             for i in ids]
    conn.close()
    assert all(uuids)
    assert len(set(uuids)) == len(uuids)  # çakışma yok


def test_deterministic_backfill_for_pre_existing_rows(tmp_path):
    # uuid kolonu olmayan eski bir SQLite'ı simüle et, sonra şema kurulumunu uygula.
    import sqlite3
    path = str(tmp_path / "old.db")
    old = database.DB_PATH
    database.DB_PATH = path
    raw = sqlite3.connect(path)
    raw.execute("CREATE TABLE kurumlar (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "kurum_adi TEXT NOT NULL UNIQUE, created_at TEXT)")
    raw.execute("INSERT INTO kurumlar (id, kurum_adi) VALUES (7, 'Eski')")
    raw.commit()
    raw.close()
    try:
        database.init_db()
        conn = database.get_connection()
        row = conn.execute("SELECT uuid FROM kurumlar WHERE id=7").fetchone()
        conn.close()
        assert row["uuid"] == "kurumlar:7"  # deterministik -> ilk sync'te eşleşir
    finally:
        database.DB_PATH = old


# ─────────────────────────────────────────────────────────────
# 3) Pull mantığı: idempotency, tombstone, FK sırası, döngü önleme
# ─────────────────────────────────────────────────────────────

def _change(tbl, op, row_uuid, payload=None, parent_uuid=None, rev=1):
    return {"tbl": tbl, "op": op, "row_uuid": row_uuid,
            "parent_uuid": parent_uuid, "payload": payload, "rev": rev,
            "device_id": "remoteDEV"}


def test_apply_incoming_insert_and_idempotency(db):
    conn = database.get_connection()
    sync._set_applying(conn, True)
    ch = _change("soru_takip", "U", "u-remote-1",
                 payload={"tarih": "2025-02-01", "ders": "Fen", "soru_sayisi": 10,
                          "dogru": 7, "yanlis": 3, "net": 6.25,
                          "created_at": "2025-02-01 00:00:00"}, rev=3)
    assert sync._apply_change_local(conn, ch) is True
    assert sync._apply_change_local(conn, ch) is True  # ikinci kez -> idempotent
    sync._set_applying(conn, False)
    conn.commit()
    rows = conn.execute("SELECT uuid, base_rev FROM soru_takip WHERE uuid='u-remote-1'").fetchall()
    # outbox'ta uygulanan değişiklik için YENİ olay OLMAMALI (döngü önleme)
    q = conn.execute("SELECT COUNT(*) AS n FROM sync_queue").fetchone()["n"]
    conn.close()
    assert len(rows) == 1          # yinelenmedi
    assert rows[0]["base_rev"] == 3
    assert q == 0                  # gelen kayıt yeni outbox üretmedi


def test_apply_delete_prevents_resurrection(db):
    conn = database.get_connection()
    sync._set_applying(conn, True)
    # Önce silme gelir
    sync._apply_change_local(conn, _change("soru_takip", "D", "ghost-1"))
    # Sonra aynı kayıt için güncelleme gelir -> tombstone yüzünden canlanmamalı
    sync._apply_change_local(conn, _change(
        "soru_takip", "U", "ghost-1",
        payload={"tarih": "2025-02-01", "ders": "Fen", "soru_sayisi": 1,
                 "dogru": 1, "yanlis": 0, "net": 1.0, "created_at": "x"}, rev=5))
    sync._set_applying(conn, False)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) AS n FROM soru_takip WHERE uuid='ghost-1'").fetchone()["n"]
    conn.close()
    assert n == 0  # silinen kayıt yeniden ortaya çıkmadı


def test_apply_child_before_parent_is_deferred(db):
    conn = database.get_connection()
    sync._set_applying(conn, True)
    # Çocuk önce gelir, ebeveyn henüz yok -> ertelenmeli (False)
    child = _change("sinav_dersleri", "U", "sd-1",
                    payload={"ders": "Fen", "soru_sayisi": 20, "dogru": 10,
                             "yanlis": 10, "net": 6.66, "__parent_uuid__": "sv-1"},
                    parent_uuid="sv-1", rev=1)
    assert sync._apply_change_local(conn, child) is False
    # Ebeveyn gelir
    parent = _change("sinavlar", "U", "sv-1",
                     payload={"sinav_adi": "Deneme", "sinav_tarihi": "2025-02-01",
                              "puan": 440.0, "genel_derece": None, "il_derece": None,
                              "ilce_derece": None, "kurum_derece": None, "sube_derece": None,
                              "notlar": None, "created_at": "x", "__parent_uuid__": None},
                     rev=1)
    assert sync._apply_change_local(conn, parent) is True
    # Çocuk tekrar denenince başarılı olmalı ve FK doğru çözülmeli
    assert sync._apply_change_local(conn, child) is True
    sync._set_applying(conn, False)
    conn.commit()
    row = conn.execute(
        "SELECT sd.sinav_id, s.uuid FROM sinav_dersleri sd "
        "JOIN sinavlar s ON s.id = sd.sinav_id WHERE sd.uuid='sd-1'").fetchone()
    conn.close()
    assert row is not None
    assert row["uuid"] == "sv-1"  # FK yerel id'ye doğru çözüldü


def test_apply_does_not_generate_outbox(db):
    # applying=1 iken yapılan ham değişiklikler outbox'a yazılmaz.
    conn = database.get_connection()
    sync._set_applying(conn, True)
    conn.execute("INSERT INTO soru_takip (tarih, ders, soru_sayisi, dogru, yanlis, net, uuid) "
                 "VALUES ('2025-01-01','Fen',10,5,5,2.5,'manual-1')")
    sync._set_applying(conn, False)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) AS n FROM sync_queue").fetchone()["n"]
    conn.close()
    assert n == 0


# ─────────────────────────────────────────────────────────────
# 4) Çevrimdışı: bağlantı yokken CRUD çalışır, olaylar kaybolmaz
# ─────────────────────────────────────────────────────────────

def test_offline_crud_preserves_pending_events(db, monkeypatch):
    database.kayit_ekle("2025-01-01", "Matematik", 20, 15, 3)
    # Neon bağlantısını zorla başarısız yap -> çevrimdışı
    monkeypatch.setattr(sync, "get_remote_connection",
                        lambda: (_ for _ in ()).throw(OSError("ağ yok")))
    result = sync.sync_now()
    assert result.offline is True
    conn = database.get_connection()
    pend = sync.pending_count(conn)
    conn.close()
    assert pend >= 1  # bekleyen olaylar korundu


# ─────────────────────────────────────────────────────────────
# 5) Ayar sınıflandırması
# ─────────────────────────────────────────────────────────────

def test_sensitive_settings_classification():
    assert sync._is_sensitive_setting("gemini_api_key")
    assert sync._is_sensitive_setting("openai_api_key")
    assert sync._is_sensitive_setting("DATABASE_URL")
    assert sync._is_sensitive_setting("my_secret_token")
    assert not sync._is_sensitive_setting("ai_provider")
    assert not sync._is_sensitive_setting("ai_model")
    assert not sync._is_sensitive_setting("theme")


# ─────────────────────────────────────────────────────────────
# 6) push() yerel defter tutması (sahte remote; Postgres gerekmez)
# ─────────────────────────────────────────────────────────────

class _FakeRemote:
    """push() içindeki Neon çağrılarını karşılayan minimal taklit."""
    def __init__(self):
        self.calls = []
        self.committed = False
        self._last = ("", None)

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self._last = (sql, params)
        return self

    def fetchone(self):
        s = self._last[0].lower()
        if "select id from" in s:
            return {"id": 1}
        if "returning rev" in s:
            return {"rev": 1}
        if "select rev" in s:
            return None  # yeni satır
        return None

    def fetchall(self):
        return []

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def test_push_marks_done_and_skips_sensitive(db):
    database.kayit_ekle("2025-01-01", "Matematik", 20, 15, 3)
    database.kaydet_ayar("ai_provider", "openai")        # senkronize edilmeli
    database.kaydet_ayar("openai_api_key", "sk-secret")  # ASLA gönderilmemeli

    conn = database.get_connection()
    device_id = sync.get_device_id(conn)
    fake = _FakeRemote()
    sent = sync.push(conn, fake, device_id)
    pend_after = sync.pending_count(conn)
    base_rev = conn.execute(
        "SELECT base_rev FROM soru_takip LIMIT 1").fetchone()["base_rev"]
    conn.close()

    assert sent >= 2
    assert pend_after == 0                 # tüm olaylar 'done'
    assert base_rev == 1                   # base_rev güncellendi
    assert fake.committed is True
    # Hassas anahtar değeri remote çağrılarına ASLA girmemeli
    blob = repr(fake.calls)
    assert "sk-secret" not in blob
    assert "openai" in blob                # güvenli ayar gönderildi
