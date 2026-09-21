"""Seed DB dari arsip mentah ATAU dari dataset publik (JSONL).

Pakai:
    python -m tools.seed /path/raw_archive.json          # format api/x/posts (butuh API)
    python -m tools.seed --from-jsonl ../dataset/tweets  # dataset publik (JSONL, tanpa API)

Impor JSONL memulihkan tweet **beserta terjemahannya** → tidak perlu memanggil
API translasi lagi. Berguna untuk: mirror, riset, atau menjalankan viewer sendiri.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db as dbm  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.source import parse_tweet  # noqa: E402


def item_from_record(rec: dict) -> dict:
    """Satu baris dataset JSONL → dict internal (setara keluaran parse_tweet)."""
    media = rec.get("media") or None
    if isinstance(media, list):
        media = [str(u) for u in media if str(u).startswith("http")] or None
    return {
        "id_str": str(rec["id_str"]),
        "member": rec["member"],
        "member_name": rec.get("member_name"),
        "avatar": rec.get("avatar"),
        "created_at": rec["created_at"],
        "text": rec.get("text") or "",
        "favorite_count": int(rec.get("favorite_count") or 0),
        "conversation_count": int(rec.get("conversation_count") or 0),
        "is_reply": bool(rec.get("is_reply")),
        "media": media,
        "quoted_tweet": rec.get("quoted_tweet") or None,
        "url": rec.get("url") or "",
        "raw": None,
    }


def iter_jsonl(path: Path):
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path", nargs="?", help="file arsip mentah (format api/x/posts)")
    ap.add_argument("--from-jsonl", metavar="PATH",
                    help="file/folder dataset publik (.jsonl) — termasuk terjemahan")
    ap.add_argument("--skip-notify", action="store_true", default=True,
                    help="tandai semua sebagai skipped (baseline) — default true")
    args = ap.parse_args()
    if not args.json_path and not args.from_jsonl:
        ap.error("butuh json_path atau --from-jsonl")

    settings = get_settings()
    conn = dbm.connect(settings.db_path)
    dbm.init_db(conn)

    translations: list[tuple[str, str]] = []
    if args.from_jsonl:
        items = []
        for rec in iter_jsonl(Path(args.from_jsonl)):
            items.append(item_from_record(rec))
            if rec.get("text_id"):
                translations.append((rec["text_id"], rec["id_str"]))
    else:
        data = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
        items = [parse_tweet(t) for t in data if t.get("id_str")]

    items = [i for i in items if i["id_str"] and i["member"]]
    items.sort(key=lambda t: t["created_at"] or "")

    new_ids: list[str] = []
    BATCH = 200
    for i in range(0, len(items), BATCH):
        new_ids.extend(dbm.upsert_tweets(conn, items[i:i + BATCH]))

    # pulihkan terjemahan dari dataset (tanpa memanggil API)
    restored = 0
    if translations:
        for text_id, id_str in translations:
            cur = conn.execute(
                "UPDATE tweets SET text_id = ?, translated_at = COALESCE(translated_at, ?) "
                "WHERE id_str = ? AND text_id IS NULL", (text_id, dbm.now_utc(), id_str)
            )
            restored += cur.rowcount
        conn.commit()

    if args.skip_notify:
        dbm.mark_skipped(conn, new_ids)
    dbm.set_meta(conn, "baseline_done", "true")
    dbm.set_meta(conn, "last_check_utc", dbm.now_utc())

    st = dbm.stats(conn)
    print(json.dumps({"seeded": len(items), "new": len(new_ids),
                      "translations_restored": restored, **st},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
