"""One-time, resumable copy of the app's SQLite data into Neon Postgres."""

import os
import sqlite3
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

import database


TABLES = (
    "db_meta",
    "soru_takip",
    "kurumlar",
    "sinavlar",
    "sinav_dersleri",
    "ayarlar",
    "karneler",
    "karne_ders_analizi",
    "karne_konu_analizi",
    "rag_chunks",
)
ID_TABLES = tuple(t for t in TABLES if t not in ("db_meta", "ayarlar"))


def _env_values():
    result = {}
    for name in (".env.local", ".env"):
        path = Path(database._get_db_dir()) / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def main():
    env = _env_values()
    sqlite_path = Path(os.environ.get("SQLITE_PATH", database.DB_PATH))
    pg_url = os.environ.get("DATABASE_URL_UNPOOLED") or env.get("DATABASE_URL_UNPOOLED")
    pg_url = pg_url or os.environ.get("DATABASE_URL") or env.get("DATABASE_URL")
    if not pg_url:
        raise SystemExit("DATABASE_URL (veya DATABASE_URL_UNPOOLED) ayarlanmamış.")
    if not sqlite_path.is_file():
        raise SystemExit(f"SQLite kaynağı bulunamadı: {sqlite_path}")

    # Ensure all application tables and indexes are present before copying.
    database.init_db()
    source = sqlite3.connect(str(sqlite_path))
    source.row_factory = sqlite3.Row
    counts = {table: source.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
              for table in TABLES}

    with psycopg.connect(pg_url, row_factory=dict_row, connect_timeout=20) as target:
        target.execute("""
            CREATE TABLE IF NOT EXISTS app_migrations (
                migration_key TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        done = target.execute(
            "SELECT 1 FROM app_migrations WHERE migration_key = %s",
            ("sqlite-to-neon-v1",),
        ).fetchone()
        if done:
            print("Migration already applied; no rows changed.")
            source.close()
            return

        # Never merge into or overwrite a pre-populated remote database.
        remote_counts = {}
        for table in TABLES:
            if table == "db_meta":
                continue  # init_db writes the current schema version there.
            remote_counts[table] = target.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"]
        occupied = {table: count for table, count in remote_counts.items() if count}
        if occupied:
            raise SystemExit(
                "Neon tablolarında zaten veri var; güvenli aktarım için durduruldu: "
                + ", ".join(f"{table}={count}" for table, count in occupied.items())
            )

        copied = {}
        for table in TABLES:
            rows = source.execute(f'SELECT * FROM "{table}"').fetchall()
            copied[table] = len(rows)
            if not rows:
                continue
            columns = [column[1] for column in source.execute(f'PRAGMA table_info("{table}")')]
            column_sql = ", ".join(f'"{column}"' for column in columns)
            placeholders = ", ".join(["%s"] * len(columns))
            sql = f'INSERT INTO "{table}" ({column_sql}) VALUES ({placeholders})'
            if table == "db_meta":
                sql += " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            target.cursor().executemany(
                sql, [tuple(row[column] for column in columns) for row in rows]
            )

        # Explicit IDs were preserved; advance each generated sequence past its current max.
        for table in ID_TABLES:
            target.execute(
                f"SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                f"GREATEST(COALESCE((SELECT MAX(id) FROM \"{table}\"), 1), 1), "
                f"EXISTS (SELECT 1 FROM \"{table}\"))",
                (table,),
            )

        target.execute(
            "INSERT INTO app_migrations (migration_key) VALUES (%s)",
            ("sqlite-to-neon-v1",),
        )

    source.close()
    for table in TABLES:
        print(f"{table}: {copied[table]} / {counts[table]} rows")
    print("SQLite-to-Neon migration committed successfully.")


if __name__ == "__main__":
    main()
