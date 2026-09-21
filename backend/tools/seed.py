"""Seed DB dari file JSON arsip mentah (format api/x/posts).

Pakai: python -m tools.seed /path/raw_archive.json [--skip-notify]
Berguna untuk dev/testing tanpa memanggil API sumber 83x.
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path")
    ap.add_argument("--skip-notify", action="store_true", default=True,
                    help="tandai semua sebagai skipped (baseline) — default true")
    args = ap.parse_args()

    settings = get_settings()
    conn = dbm.connect(settings.db_path)
    dbm.init_db(conn)

    data = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    items = [parse_tweet(t) for t in data if t.get("id_str")]
    items = [i for i in items if i["id_str"] and i["member"]]
    items.sort(key=lambda t: t["created_at"])

    new_ids: list[str] = []
    BATCH = 200
    for i in range(0, len(items), BATCH):
        new_ids.extend(dbm.upsert_tweets(conn, items[i:i + BATCH]))

    if args.skip_notify:
        dbm.mark_skipped(conn, new_ids)
    dbm.set_meta(conn, "baseline_done", "true")
    dbm.set_meta(conn, "last_check_utc", dbm.now_utc())

    st = dbm.stats(conn)
    print(json.dumps({"seeded": len(items), "new": len(new_ids), **st}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
