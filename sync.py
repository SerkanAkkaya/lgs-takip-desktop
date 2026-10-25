"""
LGS Hazırlık Takip - Senkronizasyon Katmanı

Yerel-öncelikli mimari:
  * Tüm CRUD işlemleri yerel SQLite üzerinde hızlıca yapılır.
  * Her değişiklik aynı SQLite transaction'ında outbox kuyruğuna (sync_queue)
    SQL trigger'ları ile kaydedilir -> executemany, cascade delete, doğrudan SQL ve
    yardımcı fonksiyonlar dahil TÜM yollar yakalanır.
  * `sync_now()` çift yönlü çalışır: önce yerel outbox olaylarını Neon'a gönderir
    (push), sonra Neon'daki değişiklikleri yerel SQLite'a uygular (pull).
  * Gelen değişiklikler, trigger'lar sync_control bayrağı ile bastırıldığı için
    yeni outbox olayı üretmez (sonsuz döngü önlenir).

Kimlik:
  * Her kayıt için cihazlar arası değişmeyen `uuid` kullanılır.
  * Yeni kayıtlar rastgele 128-bit uuid alır (cihazlar arası çakışma olmaz).
  * Taşınmış (migrate edilmiş) mevcut kayıtlar deterministik `tbl:id` uuid alır;
    böylece ilk senkronizasyonda yerel ve Neon'daki aynı kayıt eşleşir, kopyalanmaz.
"""

import os
import threading
import uuid as _uuid
from datetime import datetime

import database


# ─── Senkronize edilecek kullanıcı verisi tabloları ───
# Sıra önemlidir: ebeveyn tablolar çocuklardan ÖNCE gelir (foreign key düzeni).
SYNC_ORDER = [
    "kurumlar",
    "soru_takip",
    "sinavlar",
    "sinav_dersleri",
    "karneler",
    "karne_ders_analizi",
    "karne_konu_analizi",
    "rag_chunks",
]

# Her tablo için: business kolonları, ebeveyn tablo/FK kolonu, blob kolonları.
TABLE_CONFIG = {
    "kurumlar": {
        "cols": ["kurum_adi", "created_at"],
        "parent": None, "fk": None, "blobs": [],
    },
    "soru_takip": {
        "cols": ["tarih", "ders", "soru_sayisi", "dogru", "yanlis", "net", "created_at"],
        "parent": None, "fk": None, "blobs": [],
    },
    "sinavlar": {
        "cols": ["sinav_adi", "sinav_tarihi", "kurum_id", "puan", "genel_derece",
                 "il_derece", "ilce_derece", "kurum_derece", "sube_derece", "notlar", "created_at"],
        "parent": "kurumlar", "fk": "kurum_id", "blobs": [],
    },
    "sinav_dersleri": {
        "cols": ["sinav_id", "ders", "soru_sayisi", "dogru", "yanlis", "net"],
        "parent": "sinavlar", "fk": "sinav_id", "blobs": [],
    },
    "karneler": {
        "cols": ["dosya_adi", "sinav_tarihi", "kurum_adi", "sinav_adi", "raw_text", "ai_ozet", "created_at"],
        "parent": None, "fk": None, "blobs": [],
    },
    "karne_ders_analizi": {
        "cols": ["karne_id", "ders", "soru_sayisi", "dogru", "yanlis", "bos", "net", "basari_yuzdesi"],
        "parent": "karneler", "fk": "karne_id", "blobs": [],
    },
    "karne_konu_analizi": {
        "cols": ["karne_id", "ders", "konu", "kazanim", "dogru", "yanlis", "bos", "toplam"],
        "parent": "karneler", "fk": "karne_id", "blobs": [],
    },
    "rag_chunks": {
        "cols": ["karne_id", "chunk_text", "embedding", "provider", "chunk_index", "created_at"],
        "parent": "karneler", "fk": "karne_id", "blobs": ["embedding"],
    },
}

# ayarlar tablosunda cihaza/özel sırra ait anahtarlar ASLA senkronize edilmez.
_SENSITIVE_SETTING_KEYS = {"gemini_api_key", "openai_api_key"}
_SENSITIVE_SETTING_SUBSTRINGS = ("api_key", "apikey", "secret", "password", "parola",
                                 "token", "database_url", "_url", "credential")

# Senkronize edilmeyen dahili tablolar (cihaz başına yerel kalır).
INTERNAL_TABLES = {"db_meta", "sync_queue", "sync_state", "sync_control",
                   "sync_conflicts", "sync_tombstones"}

# Tek seferde yalnızca bir senkronizasyon çalışsın (otomatik + manuel yarışı önlenir).
_sync_lock = threading.Lock()


def _is_sensitive_setting(key: str) -> bool:
    k = (key or "").lower()
    if k in _SENSITIVE_SETTING_KEYS:
        return True
    return any(part in k for part in _SENSITIVE_SETTING_SUBSTRINGS)


# ═══════════════════════════════════════════════════════════
# YEREL ŞEMA (SQLite): uuid kolonları, outbox, trigger'lar
# ═══════════════════════════════════════════════════════════

def ensure_local_sync_schema(conn):
    """SQLite tarafında senkronizasyon altyapısını idempotent biçimde hazırla.

    init_db() içinden, tablolar oluşturulduktan sonra aynı bağlantıda çağrılır.
    """
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_control (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            applying INTEGER NOT NULL DEFAULT 0
        )
    """)
    cur.execute("INSERT OR IGNORE INTO sync_control (id, applying) VALUES (1, 0)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_queue (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            tbl TEXT NOT NULL,
            op TEXT NOT NULL,
            row_uuid TEXT NOT NULL,
            local_id INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON sync_queue(status, seq)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_tombstones (
            tbl TEXT NOT NULL,
            row_uuid TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (tbl, row_uuid)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tbl TEXT, row_uuid TEXT, base_rev INTEGER, remote_rev INTEGER,
            detail TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)

    # Cihaz kimliği (bir kez üretilir, sabit kalır).
    row = cur.execute("SELECT value FROM sync_state WHERE key = 'device_id'").fetchone()
    if not row:
        did = _uuid.uuid4().hex
        cur.execute("INSERT INTO sync_state (key, value) VALUES ('device_id', ?)", (did,))

    # Kullanıcı verisi tablolarına uuid + base_rev kolonlarını ekle ve geriye doldur.
    for tbl in SYNC_ORDER:
        existing = {c["name"] for c in cur.execute(f"PRAGMA table_info({tbl})").fetchall()}
        if "uuid" not in existing:
            cur.execute(f"ALTER TABLE {tbl} ADD COLUMN uuid TEXT")
        if "base_rev" not in existing:
            cur.execute(f"ALTER TABLE {tbl} ADD COLUMN base_rev INTEGER NOT NULL DEFAULT 0")
        # Taşınmış mevcut kayıtlar için deterministik uuid (tbl:id) -> ilk sync'te eşleşir.
        cur.execute(f"UPDATE {tbl} SET uuid = '{tbl}:' || id WHERE uuid IS NULL OR uuid = ''")
        cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{tbl}_uuid ON {tbl}(uuid)")

    _create_triggers(cur)
    conn.commit()


def _create_triggers(cur):
    """Outbox trigger'larını oluştur. sync_control.applying=1 iken bastırılır."""
    guard = "(SELECT applying FROM sync_control WHERE id = 1) = 0"
    for tbl in SYNC_ORDER:
        # INSERT: uuid ata (yoksa) ve ekleme olayı kuyruğa yaz.
        cur.execute(f"""
            CREATE TRIGGER IF NOT EXISTS sq_{tbl}_ai AFTER INSERT ON {tbl}
            WHEN {guard}
            BEGIN
                UPDATE {tbl} SET uuid = lower(hex(randomblob(16)))
                    WHERE id = NEW.id AND (uuid IS NULL OR uuid = '');
                INSERT INTO sync_queue (tbl, op, row_uuid, local_id)
                    SELECT '{tbl}', 'I', uuid, id FROM {tbl} WHERE id = NEW.id;
            END;
        """)
        # UPDATE: yalnızca gerçek güncellemeler (uuid zaten atanmış) olay üretir.
        cur.execute(f"""
            CREATE TRIGGER IF NOT EXISTS sq_{tbl}_au AFTER UPDATE ON {tbl}
            WHEN {guard} AND OLD.uuid IS NOT NULL AND OLD.uuid <> ''
            BEGIN
                INSERT INTO sync_queue (tbl, op, row_uuid, local_id)
                    VALUES ('{tbl}', 'U', OLD.uuid, NEW.id);
            END;
        """)
        # DELETE: tombstone + silme olayı.
        cur.execute(f"""
            CREATE TRIGGER IF NOT EXISTS sq_{tbl}_ad AFTER DELETE ON {tbl}
            WHEN {guard} AND OLD.uuid IS NOT NULL AND OLD.uuid <> ''
            BEGIN
                INSERT INTO sync_queue (tbl, op, row_uuid, local_id)
                    VALUES ('{tbl}', 'D', OLD.uuid, OLD.id);
                INSERT OR IGNORE INTO sync_tombstones (tbl, row_uuid)
                    VALUES ('{tbl}', OLD.uuid);
            END;
        """)

    # ayarlar: integer id yok, anahtar üzerinden kimlik. Hassas anahtarlar push'ta elenir.
    cur.execute(f"""
        CREATE TRIGGER IF NOT EXISTS sq_ayarlar_ai AFTER INSERT ON ayarlar
        WHEN {guard}
        BEGIN
            INSERT INTO sync_queue (tbl, op, row_uuid, local_id)
                VALUES ('ayarlar', 'U', 'ayar:' || NEW.key, NULL);
        END;
    """)
    cur.execute(f"""
        CREATE TRIGGER IF NOT EXISTS sq_ayarlar_au AFTER UPDATE ON ayarlar
        WHEN {guard}
        BEGIN
            INSERT INTO sync_queue (tbl, op, row_uuid, local_id)
                VALUES ('ayarlar', 'U', 'ayar:' || NEW.key, NULL);
        END;
    """)
    cur.execute(f"""
        CREATE TRIGGER IF NOT EXISTS sq_ayarlar_ad AFTER DELETE ON ayarlar
        WHEN {guard}
        BEGIN
            INSERT INTO sync_queue (tbl, op, row_uuid, local_id)
                VALUES ('ayarlar', 'D', 'ayar:' || OLD.key, NULL);
        END;
    """)


# ─── Yerel yardımcılar ───

def _set_applying(conn, value):
    conn.execute("UPDATE sync_control SET applying = ? WHERE id = 1", (1 if value else 0,))


def get_state(conn, key, default=None):
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn, key, value):
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def get_device_id(conn):
    return get_state(conn, "device_id")


def pending_count(conn):
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sync_queue WHERE status = 'pending'"
    ).fetchone()
    return row["n"] if row else 0


def get_sync_status(conn=None):
    """GUI için senkronizasyon durumu özeti."""
    own = False
    if conn is None:
        conn = database.get_connection()
        own = True
    try:
        return {
            "pending": pending_count(conn),
            "device_id": get_device_id(conn),
            "last_sync_at": get_state(conn, "last_sync_at"),
            "last_status": get_state(conn, "last_status"),
            "conflicts": conn.execute("SELECT COUNT(*) AS n FROM sync_conflicts").fetchone()["n"],
        }
    finally:
        if own:
            conn.close()


# ═══════════════════════════════════════════════════════════
# PAYLOAD / VERİ DÖNÜŞÜMLERİ
# ═══════════════════════════════════════════════════════════

def _row_payload(tbl, row, parent_uuid):
    """Yerel satırı, FK'leri ebeveyn uuid ile ifade eden taşınabilir payload'a çevir."""
    cfg = TABLE_CONFIG[tbl]
    payload = {}
    for col in cfg["cols"]:
        if col == cfg["fk"]:
            continue
        val = row[col]
        if col in cfg["blobs"] and val is not None:
            val = bytes(val).hex()  # blob -> hex metin
        payload[col] = val
    if cfg["fk"]:
        payload["__parent_uuid__"] = parent_uuid
    return payload


def _payload_to_remote_values(tbl, payload, remote, parent_uuid):
    """Payload'ı Neon INSERT/UPDATE için (kolon, değer) listesine çevir.

    FK kolonu, ebeveyn uuid'inden Neon'daki yerel id'ye çözülür.
    """
    cfg = TABLE_CONFIG[tbl]
    cols, vals = [], []
    for col in cfg["cols"]:
        if col == cfg["fk"]:
            pid = None
            if parent_uuid:
                r = remote.execute(
                    f"SELECT id FROM {cfg['parent']} WHERE uuid = %s", (parent_uuid,)
                ).fetchone()
                pid = r["id"] if r else None
            cols.append(col)
            vals.append(pid)
            continue
        v = payload.get(col)
        if col in cfg["blobs"] and v is not None:
            v = bytes.fromhex(v)
        cols.append(col)
        vals.append(v)
    return cols, vals


# ═══════════════════════════════════════════════════════════
# UZAK ŞEMA (Neon Postgres) — güvenli, tekrar çalıştırılabilir migration
# ═══════════════════════════════════════════════════════════

def get_remote_connection():
    import psycopg
    from psycopg.rows import dict_row
    url = database._get_database_url()
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=20)


def ensure_remote_sync_schema(remote):
    """Neon tarafında uuid/rev kolonlarını, değişiklik günlüğünü ve indeksleri kur."""
    cur = remote.cursor()
    for tbl in SYNC_ORDER:
        cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS uuid TEXT")
        cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS rev INTEGER NOT NULL DEFAULT 1")
        cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS last_device TEXT")
        cur.execute(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS deleted INTEGER NOT NULL DEFAULT 0")
        # Taşınmış kayıtlar için deterministik uuid -> yerel ile aynı şema.
        cur.execute(f"UPDATE {tbl} SET uuid = '{tbl}:' || id WHERE uuid IS NULL OR uuid = ''")
        cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_{tbl}_uuid ON {tbl}(uuid)")

    # ayarlar tablosunda uuid yerine key kullanılır; yine de rev/device izlenir.
    cur.execute("ALTER TABLE ayarlar ADD COLUMN IF NOT EXISTS rev INTEGER NOT NULL DEFAULT 1")
    cur.execute("ALTER TABLE ayarlar ADD COLUMN IF NOT EXISTS last_device TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sync_changes (
            seq BIGSERIAL PRIMARY KEY,
            tbl TEXT NOT NULL,
            op TEXT NOT NULL,
            row_uuid TEXT NOT NULL,
            parent_uuid TEXT,
            payload JSONB,
            rev INTEGER,
            device_id TEXT NOT NULL,
            committed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_sync_changes_seq ON sync_changes(seq)")
    remote.commit()


# ═══════════════════════════════════════════════════════════
# PUSH: yerel outbox -> Neon
# ═══════════════════════════════════════════════════════════

def _remote_record_change(remote, tbl, op, row_uuid, parent_uuid, payload, rev, device_id):
    import json
    remote.execute(
        "INSERT INTO sync_changes (tbl, op, row_uuid, parent_uuid, payload, rev, device_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (tbl, op, row_uuid, parent_uuid,
         json.dumps(payload, ensure_ascii=False) if payload is not None else None,
         rev, device_id),
    )


def _remote_upsert(remote, tbl, row_uuid, parent_uuid, payload, base_rev, device_id):
    cfg = TABLE_CONFIG[tbl]
    cols, vals = _payload_to_remote_values(tbl, payload, remote, parent_uuid)
    old = remote.execute(
        f"SELECT rev, last_device, deleted FROM {tbl} WHERE uuid = %s", (row_uuid,)
    ).fetchone()
    conflict = False
    if old is None:
        new_rev = 1
        all_cols = ["uuid"] + cols + ["rev", "last_device", "deleted"]
        ph = ", ".join(["%s"] * len(all_cols))
        remote.execute(
            f"INSERT INTO {tbl} ({', '.join(all_cols)}) VALUES ({ph})",
            [row_uuid] + vals + [new_rev, device_id, 0],
        )
    else:
        new_rev = (old["rev"] or 1) + 1
        if (old["rev"] or 0) != (base_rev or 0) and old["last_device"] != device_id:
            conflict = True
        set_sql = ", ".join(f"{c} = %s" for c in cols)
        remote.execute(
            f"UPDATE {tbl} SET {set_sql}, rev = %s, last_device = %s, deleted = 0 WHERE uuid = %s",
            vals + [new_rev, device_id, row_uuid],
        )
    _remote_record_change(remote, tbl, "U", row_uuid, parent_uuid, payload, new_rev, device_id)
    return new_rev, conflict


def _remote_delete(remote, tbl, row_uuid, device_id):
    old = remote.execute(f"SELECT rev FROM {tbl} WHERE uuid = %s", (row_uuid,)).fetchone()
    new_rev = ((old["rev"] if old else 0) or 0) + 1
    remote.execute(
        f"UPDATE {tbl} SET deleted = 1, rev = %s, last_device = %s WHERE uuid = %s",
        (new_rev, device_id, row_uuid),
    )
    _remote_record_change(remote, tbl, "D", row_uuid, None, None, new_rev, device_id)
    return new_rev


def _remote_setting_upsert(remote, key, value, device_id):
    remote.execute(
        "INSERT INTO ayarlar (key, value, rev, last_device) VALUES (%s, %s, 1, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "
        "rev = ayarlar.rev + 1, last_device = EXCLUDED.last_device "
        "RETURNING rev", (key, value, device_id),
    )
    row = remote.fetchone()
    rev = row["rev"] if row else 1
    _remote_record_change(remote, "ayarlar", "U", "ayar:" + key, None,
                          {"key": key, "value": value}, rev, device_id)


def _remote_setting_delete(remote, key, device_id):
    remote.execute("DELETE FROM ayarlar WHERE key = %s", (key,))
    _remote_record_change(remote, "ayarlar", "D", "ayar:" + key, None, None, 0, device_id)


def push(local, remote, device_id):
    """Yerel outbox'taki bekleyen olayları Neon'a gönder. Gönderilen olay sayısını döndür."""
    cur = local.cursor()
    events = cur.execute(
        "SELECT seq, tbl, op, row_uuid FROM sync_queue WHERE status = 'pending' ORDER BY seq"
    ).fetchall()
    if not events:
        return 0

    processed = []       # (seq,)
    rev_updates = []     # (tbl, row_uuid, new_rev)
    conflicts = []       # (tbl, row_uuid, base_rev, new_rev)
    sent = 0

    for ev in events:
        tbl, op, ruid = ev["tbl"], ev["op"], ev["row_uuid"]

        if tbl == "ayarlar":
            key = ruid.split(":", 1)[1] if ":" in ruid else ruid
            if _is_sensitive_setting(key):
                processed.append(ev["seq"])  # hassas: gönderme, kuyruğu temizle
                continue
            if op == "D":
                _remote_setting_delete(remote, key, device_id)
            else:
                r = cur.execute("SELECT value FROM ayarlar WHERE key = ?", (key,)).fetchone()
                if r is None:
                    processed.append(ev["seq"])
                    continue
                _remote_setting_upsert(remote, key, r["value"], device_id)
            processed.append(ev["seq"])
            sent += 1
            continue

        if op == "D":
            _remote_delete(remote, tbl, ruid, device_id)
            processed.append(ev["seq"])
            sent += 1
            continue

        # I / U -> güncel yerel satırı oku (birden çok güncelleme birleştirilir)
        row = cur.execute(f"SELECT * FROM {tbl} WHERE uuid = ?", (ruid,)).fetchone()
        if row is None:
            processed.append(ev["seq"])  # sonradan silinmiş; D olayı halleder
            continue
        cfg = TABLE_CONFIG[tbl]
        parent_uuid = None
        if cfg["fk"] and row[cfg["fk"]] is not None:
            p = cur.execute(
                f"SELECT uuid FROM {cfg['parent']} WHERE id = ?", (row[cfg["fk"]],)
            ).fetchone()
            parent_uuid = p["uuid"] if p else None
        payload = _row_payload(tbl, row, parent_uuid)
        base_rev = row["base_rev"] or 0
        new_rev, conflict = _remote_upsert(remote, tbl, ruid, parent_uuid, payload, base_rev, device_id)
        rev_updates.append((tbl, ruid, new_rev))
        if conflict:
            conflicts.append((tbl, ruid, base_rev, new_rev))
        processed.append(ev["seq"])
        sent += 1

    # Önce Neon commit -> ancak başarıyla kaydedildikten sonra yerelde 'done' işaretle.
    remote.commit()

    _set_applying(local, True)
    try:
        for tbl, ruid, new_rev in rev_updates:
            cur.execute(f"UPDATE {tbl} SET base_rev = ? WHERE uuid = ?", (new_rev, ruid))
        for tbl, ruid, base_rev, new_rev in conflicts:
            cur.execute(
                "INSERT INTO sync_conflicts (tbl, row_uuid, base_rev, remote_rev, detail) "
                "VALUES (?, ?, ?, ?, ?)",
                (tbl, ruid, base_rev, new_rev,
                 "Eşzamanlı uzak değişiklik tespit edildi; yerel sürüm gönderildi (LWW)."),
            )
        if processed:
            cur.executemany(
                "UPDATE sync_queue SET status = 'done' WHERE seq = ?",
                [(s,) for s in processed],
            )
    finally:
        _set_applying(local, False)
    local.commit()
    return sent


# ═══════════════════════════════════════════════════════════
# PULL: Neon değişiklik günlüğü -> yerel SQLite
# ═══════════════════════════════════════════════════════════

def _apply_change_local(local, change):
    """Tek bir uzak değişikliği yerel SQLite'a uygula. (applying=1 altında çağrılır.)

    Ebeveyn kayıt henüz yoksa False döndürür (sonradan tekrar denenir).
    """
    import json
    tbl = change["tbl"]
    op = change["op"]
    ruid = change["row_uuid"]
    rev = change["rev"]
    payload = change["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)

    cur = local.cursor()

    if tbl == "ayarlar":
        key = ruid.split(":", 1)[1] if ":" in ruid else ruid
        if _is_sensitive_setting(key):
            return True  # hassas ayar yerelde değiştirilmez
        if op == "D":
            cur.execute("DELETE FROM ayarlar WHERE key = ?", (key,))
        else:
            val = (payload or {}).get("value", "")
            cur.execute(
                "INSERT INTO ayarlar (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, val))
        return True

    cfg = TABLE_CONFIG[tbl]

    if op == "D":
        cur.execute(f"DELETE FROM {tbl} WHERE uuid = ?", (ruid,))
        cur.execute("INSERT OR IGNORE INTO sync_tombstones (tbl, row_uuid) VALUES (?, ?)", (tbl, ruid))
        return True

    # FK -> yerel ebeveyn id çöz
    local_fk = None
    if cfg["fk"]:
        puid = (payload or {}).get("__parent_uuid__")
        if puid:
            p = cur.execute(f"SELECT id FROM {cfg['parent']} WHERE uuid = ?", (puid,)).fetchone()
            if not p:
                return False  # ebeveyn henüz gelmedi -> ertele
            local_fk = p["id"]

    # Silinmiş (tombstone) kaydı yeniden canlandırma
    ts = cur.execute(
        "SELECT 1 FROM sync_tombstones WHERE tbl = ? AND row_uuid = ?", (tbl, ruid)
    ).fetchone()
    if ts:
        return True

    values = {}
    for col in cfg["cols"]:
        if col == cfg["fk"]:
            values[col] = local_fk
        else:
            v = (payload or {}).get(col)
            if col in cfg["blobs"] and v is not None:
                v = bytes.fromhex(v)
            values[col] = v

    existing = cur.execute(f"SELECT id FROM {tbl} WHERE uuid = ?", (ruid,)).fetchone()
    if existing:
        set_sql = ", ".join(f"{c} = ?" for c in values)
        cur.execute(
            f"UPDATE {tbl} SET {set_sql}, base_rev = ? WHERE uuid = ?",
            list(values.values()) + [rev, ruid],
        )
    else:
        cols = list(values.keys()) + ["uuid", "base_rev"]
        ph = ", ".join(["?"] * len(cols))
        cur.execute(
            f"INSERT INTO {tbl} ({', '.join(cols)}) VALUES ({ph})",
            list(values.values()) + [ruid, rev],
        )
    return True


def pull(local, remote, device_id):
    """Neon'daki (başka cihazlara ait) değişiklikleri yerel SQLite'a uygula."""
    cp = int(get_state(local, "last_pull_seq", "0") or 0)
    rows = remote.execute(
        "SELECT seq, tbl, op, row_uuid, parent_uuid, payload, rev, device_id "
        "FROM sync_changes WHERE seq > %s AND device_id <> %s ORDER BY seq",
        (cp, device_id),
    ).fetchall()
    if not rows:
        return 0

    applied = 0
    _set_applying(local, True)
    try:
        deferred = []
        for ch in rows:
            if not _apply_change_local(local, ch):
                deferred.append(ch)
            else:
                applied += 1
        # Ebeveyni sonradan gelen çocuklar için tekrar dene (ilerleme oldukça).
        progress = True
        while deferred and progress:
            progress = False
            still = []
            for ch in deferred:
                if _apply_change_local(local, ch):
                    applied += 1
                    progress = True
                else:
                    still.append(ch)
            deferred = still
        # İmleci yalnızca güvenli biçimde işlenen son seq'e taşı.
        max_seq = rows[-1]["seq"]
        set_state(local, "last_pull_seq", str(max_seq))
    finally:
        _set_applying(local, False)
    local.commit()
    return applied


# ═══════════════════════════════════════════════════════════
# ÜST SEVİYE: çift yönlü senkronizasyon (tek-uçuş kilidi ile)
# ═══════════════════════════════════════════════════════════

class SyncResult:
    def __init__(self, ok=False, pushed=0, pulled=0, pending_before=0,
                 skipped=False, error=None, offline=False, conflicts=0):
        self.ok = ok
        self.pushed = pushed
        self.pulled = pulled
        self.pending_before = pending_before
        self.skipped = skipped
        self.error = error
        self.offline = offline
        self.conflicts = conflicts

    def summary(self):
        if self.skipped:
            return "Zaten bir senkronizasyon çalışıyor."
        if self.offline:
            return ("Senkronizasyon tamamlanamadı (çevrimdışı). "
                    "Yerel çalışmalarınız korundu. Daha sonra tekrar deneyin.")
        if not self.ok:
            return (f"Senkronizasyon tamamlanamadı. Yerel çalışmalarınız korundu. "
                    f"Hata: {self.error}")
        msg = f"Senkronizasyon tamamlandı. Gönderilen: {self.pushed}, alınan: {self.pulled}."
        if self.conflicts:
            msg += f" ({self.conflicts} çakışma kaydedildi.)"
        return msg


def is_running():
    return _sync_lock.locked()


def sync_now():
    """Çift yönlü senkronizasyon: push -> pull. Tek anda yalnızca biri çalışır."""
    if not _sync_lock.acquire(blocking=False):
        return SyncResult(skipped=True)

    local = None
    remote = None
    try:
        local = database.get_connection()
        device_id = get_device_id(local)
        pending_before = pending_count(local)

        try:
            remote = get_remote_connection()
        except Exception as exc:  # ağ/DB erişilemez -> çevrimdışı, yerel kullanım sürer
            set_state(local, "last_status", "offline")
            local.commit()
            return SyncResult(ok=False, offline=True, error=str(exc),
                              pending_before=pending_before)

        ensure_remote_sync_schema(remote)
        pushed = push(local, remote, device_id)
        pulled = pull(local, remote, device_id)

        conflicts = local.execute("SELECT COUNT(*) AS n FROM sync_conflicts").fetchone()["n"]
        set_state(local, "last_sync_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        set_state(local, "last_status", "ok")
        local.commit()
        return SyncResult(ok=True, pushed=pushed, pulled=pulled,
                          pending_before=pending_before, conflicts=conflicts)
    except Exception as exc:
        try:
            if remote is not None:
                remote.rollback()
        except Exception:
            pass
        try:
            if local is not None:
                _set_applying(local, False)
                set_state(local, "last_status", "error")
                local.commit()
        except Exception:
            pass
        return SyncResult(ok=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        try:
            if remote is not None:
                remote.close()
        finally:
            if local is not None:
                local.close()
            _sync_lock.release()
