"""
GÖREV 1 — Tek seferlik manuel aktarım: Neon `sinavlar` -> yerel SQLite.

Bu betik KALICI senkronizasyonun yerine geçmez; yalnızca Neon'da güncel olan
`sinavlar` verisini yerel SQLite'a güvenli, idempotent ve atomik biçimde yansıtır.

Güvenlik ilkeleri:
  * Neon'da HİÇBİR kayıt silinmez/değiştirilmez (yalnızca okunur).
  * Yerel kayıtlar yalnızca `uuid` kesin eşleştiğinde güncellenir; farklı kayıtlar
    birleştirilmez. Yerelde olup Neon'da olmayan kayıtlara dokunulmaz.
  * FK (`kurum_id`) yerelde geçerli değilse ilişki UYDURULMAZ; işlem durur ve raporlanır
    (veya `--include-parents` ile yalnızca gereken ebeveyn kurumlar atomik olarak eklenir).
  * Aktarım, trigger'lar `sync_control.applying=1` ile bastırıldığı için yeni outbox
    (sync_queue) olayı üretmez -> Neon'dan gelen kayıtlar yanlışlıkla geri gönderilmez.
  * Varsayılan mod DRY-RUN (hiçbir şey yazılmaz). Gerçek aktarım için `--apply`.

Kullanım:
    python sync_sinavlar_manual.py                      # dry-run rapor
    python sync_sinavlar_manual.py --apply              # uygula (FK eksikse durur)
    python sync_sinavlar_manual.py --apply --include-parents  # eksik ebeveyn kurumları da ekle
"""

import argparse
import shutil
from datetime import datetime

import database
import sync

# sinavlar'ın karşılaştırılacak iş kolonları (id/kurum_id hariç; kurum, uuid üzerinden karşılaştırılır)
_BIZ_COLS = ["sinav_adi", "sinav_tarihi", "puan", "genel_derece", "il_derece",
             "ilce_derece", "kurum_derece", "sube_derece", "notlar", "created_at"]


class ParentMissingError(Exception):
    pass


def _load_neon_sinavlar(remote):
    return remote.execute(
        "SELECT s.*, k.uuid AS kurum_uuid, k.kurum_adi AS parent_kurum_adi "
        "FROM sinavlar s LEFT JOIN kurumlar k ON s.kurum_id = k.id "
        "WHERE COALESCE(s.deleted, 0) = 0 ORDER BY s.uuid"
    ).fetchall()


def _local_maps(local):
    loc = {r["uuid"]: r for r in local.execute("SELECT * FROM sinavlar").fetchall()}
    kur = {r["uuid"]: r["id"] for r in local.execute("SELECT uuid, id FROM kurumlar").fetchall()}
    return loc, kur


def _differs(neon_row, local_row, kur_map):
    """İş kolonları veya kurum ilişkisi farklı mı?"""
    for c in _BIZ_COLS:
        nv = neon_row[c]
        lv = local_row[c]
        if (nv if nv is not None else None) != (lv if lv is not None else None):
            return True
    # kurum karşılaştırması uuid üzerinden
    want_kurum = neon_row["kurum_uuid"]
    have_kurum_id = local_row["kurum_id"]
    have_kurum_uuid = None
    for u, i in kur_map.items():
        if i == have_kurum_id:
            have_kurum_uuid = u
            break
    return want_kurum != have_kurum_uuid


def analyze(local, remote):
    """Dry-run analizi; neyin ekleneceğini/güncelleneceğini/aynı olduğunu belirler."""
    neon = _load_neon_sinavlar(remote)
    loc, kur = _local_maps(local)

    report = {
        "neon_total": len(neon),
        "local_total": len(loc),
        "to_insert": [], "to_update": [], "same": [],
        "local_only": sorted(set(loc) - {n["uuid"] for n in neon}),
        "missing_parents": {},   # kurum_uuid -> kurum_adi (yerelde yok)
        "fk_blocked": [],        # ebeveyni olmayan sinav uuid'leri
        "ambiguous": [],         # uuid'siz Neon kayıtları (olmamalı)
    }

    for n in neon:
        ruid = n["uuid"]
        if not ruid:
            report["ambiguous"].append(f"neon_id={n['id']} ({n['sinav_adi']})")
            continue
        kurum_uuid = n["kurum_uuid"]
        if kurum_uuid and kurum_uuid not in kur:
            report["missing_parents"][kurum_uuid] = n["parent_kurum_adi"]
            report["fk_blocked"].append(ruid)
        if ruid not in loc:
            report["to_insert"].append(ruid)
        elif _differs(n, loc[ruid], kur):
            report["to_update"].append(ruid)
        else:
            report["same"].append(ruid)
    return report, neon


def _fetch_neon_kurum(remote, kurum_uuid):
    return remote.execute(
        "SELECT uuid, kurum_adi, created_at FROM kurumlar WHERE uuid = %s", (kurum_uuid,)
    ).fetchone()


def apply_transfer(local, remote, include_parents=False):
    """Aktarımı atomik ve idempotent biçimde uygula. Sonuç sayaçlarını döndürür."""
    report, neon = analyze(local, remote)
    result = {"inserted": 0, "updated": 0, "same": len(report["same"]),
              "parents_inserted": 0, "queue_before": 0, "queue_after": 0}

    result["queue_before"] = local.execute(
        "SELECT COUNT(*) AS n FROM sync_queue").fetchone()["n"]

    if report["ambiguous"]:
        raise ParentMissingError(
            "Neon'da uuid'siz sinav kaydı var; güvenli eşleştirme yapılamaz: "
            + ", ".join(report["ambiguous"]))

    cur = local.cursor()
    sync._set_applying(local, True)   # trigger'ları bastır -> yeni outbox olayı üretme
    try:
        # Gereken eksik ebeveyn kurumlar
        if report["missing_parents"]:
            if not include_parents:
                raise ParentMissingError(
                    "Şu sinav kayıtlarının kurumu yerelde yok, ilişki uydurulmayacak: "
                    + ", ".join(report["fk_blocked"])
                    + " | Eksik kurumlar: "
                    + ", ".join(f"{u}={ad}" for u, ad in report["missing_parents"].items())
                    + " | --include-parents ile yalnızca bu kurumları ekleyebilirsiniz.")
            for kurum_uuid in report["missing_parents"]:
                nk = _fetch_neon_kurum(remote, kurum_uuid)
                if nk is None:
                    raise ParentMissingError(f"Neon'da kurum bulunamadı: {kurum_uuid}")
                exists = cur.execute(
                    "SELECT 1 FROM kurumlar WHERE uuid = ?", (kurum_uuid,)).fetchone()
                if not exists:
                    cur.execute(
                        "INSERT INTO kurumlar (kurum_adi, created_at, uuid, base_rev) "
                        "VALUES (?, ?, ?, 0)",
                        (nk["kurum_adi"], nk["created_at"], kurum_uuid))
                    result["parents_inserted"] += 1

        # Ebeveyn eklemelerinden sonra kurum haritasını tazele
        _, kur = _local_maps(local)

        for n in neon:
            ruid = n["uuid"]
            if not ruid:
                continue
            kurum_uuid = n["kurum_uuid"]
            local_kurum_id = None
            if kurum_uuid:
                local_kurum_id = kur.get(kurum_uuid)
                if local_kurum_id is None:
                    raise ParentMissingError(
                        f"{ruid} için kurum {kurum_uuid} yerelde yok; işlem durduruldu.")

            loc, _ = _local_maps(local)
            vals = [n[c] for c in _BIZ_COLS]
            if ruid not in loc:
                cols = _BIZ_COLS + ["kurum_id", "uuid", "base_rev"]
                ph = ", ".join(["?"] * len(cols))
                cur.execute(
                    f"INSERT INTO sinavlar ({', '.join(cols)}) VALUES ({ph})",
                    vals + [local_kurum_id, ruid, n["rev"] or 0])
                result["inserted"] += 1
            elif ruid in report["to_update"]:
                set_sql = ", ".join(f"{c} = ?" for c in _BIZ_COLS)
                cur.execute(
                    f"UPDATE sinavlar SET {set_sql}, kurum_id = ?, base_rev = ? WHERE uuid = ?",
                    vals + [local_kurum_id, n["rev"] or 0, ruid])
                result["updated"] += 1

        sync._set_applying(local, False)
        local.commit()
    except Exception:
        sync._set_applying(local, False)
        local.rollback()
        raise

    result["queue_after"] = local.execute(
        "SELECT COUNT(*) AS n FROM sync_queue").fetchone()["n"]
    return result


def _print_report(report):
    print("=" * 62)
    print("DRY-RUN RAPORU — Neon sinavlar -> yerel SQLite")
    print("=" * 62)
    print(f"Neon aktif sinavlar : {report['neon_total']}")
    print(f"Yerel sinavlar      : {report['local_total']}")
    print(f"Eklenecek (Neon'da var, yerelde yok) : {len(report['to_insert'])}")
    print(f"Güncellenecek (uuid eşleşti, içerik farklı): {len(report['to_update'])}")
    print(f"Zaten aynı          : {len(report['same'])}")
    print(f"Yalnızca yerelde (dokunulmayacak)    : {len(report['local_only'])}")
    if report["missing_parents"]:
        print("\n!! FK ENGELİ — yerelde olmayan ebeveyn kurumlar:")
        for u, ad in report["missing_parents"].items():
            print(f"   {u} = {ad}")
        print(f"   Etkilenen sinav kayıtları: {report['fk_blocked']}")
        print("   -> --include-parents olmadan bu kayıtlar EKLENMEZ (ilişki uydurulmaz).")
    if report["ambiguous"]:
        print("\n!! Belirsiz (uuid'siz) Neon kayıtları:", report["ambiguous"])
    print("=" * 62)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Gerçek aktarımı uygula (varsayılan: dry-run)")
    ap.add_argument("--include-parents", action="store_true",
                    help="Gereken eksik ebeveyn kurumları da ekle")
    args = ap.parse_args()

    database.init_db()
    local = database.get_connection()
    try:
        try:
            remote = sync.get_remote_connection()
        except Exception as exc:
            print(f"Neon bağlantısı kurulamadı: {type(exc).__name__}: {exc}")
            print("Gerçek aktarım yapılamadı. Lütfen bağlantıyı kontrol edin.")
            return

        report, _ = analyze(local, remote)
        _print_report(report)

        if not args.apply:
            print("\nDRY-RUN modu: hiçbir değişiklik yapılmadı. Uygulamak için --apply ekleyin.")
            remote.close()
            return

        # Gerçek aktarım öncesi yerel yedek
        backup = database.DB_PATH + "." + datetime.now().strftime("%Y%m%d_%H%M%S") + ".bak"
        shutil.copy2(database.DB_PATH, backup)
        print(f"\nYerel yedek alındı: {backup}")

        res = apply_transfer(local, remote, include_parents=args.include_parents)
        print("\n--- UYGULAMA SONUCU ---")
        print(f"Eklenen sinav   : {res['inserted']}")
        print(f"Güncellenen     : {res['updated']}")
        print(f"Zaten aynı      : {res['same']}")
        print(f"Eklenen kurum   : {res['parents_inserted']}")
        print(f"sync_queue (önce/sonra): {res['queue_before']} / {res['queue_after']}  "
              f"(fark {res['queue_after'] - res['queue_before']} — 0 olmalı)")
        remote.close()
    finally:
        local.close()


if __name__ == "__main__":
    main()
