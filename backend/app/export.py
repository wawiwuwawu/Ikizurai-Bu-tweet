"""Ekspor DB → dataset JSON publik (folder `dataset/` di root repo).

Struktur keluaran:
  dataset/tweets/YYYY-MM.jsonl   satu tweet per baris, urut naik (created_at, id_str)
  dataset/members.json           metadata member (nama, warna resmi, jumlah tweet)
  dataset/stats.json             ringkasan + waktu ekspor
  dataset/index.json             manifest bulan (dipakai viewer mode static)

Prinsip:
- DB SQLite = satu sumber kebenaran → ekspor deterministik & idempoten.
- Atomic write (tmp + os.replace): konsumen/git tidak pernah melihat file setengah jadi.
- File TIDAK ditulis ulang bila isinya identik → diff git tetap bersih.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import db as dbm
from .members import MEMBERS, member_info

EXPORT_FIELDS = (
    "id_str", "member", "member_name", "avatar", "created_at", "text", "text_id",
    "favorite_count", "conversation_count", "is_reply", "media", "url",
)


def record_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """Satu baris DB → dict ringkas untuk dataset publik."""
    media = None
    if row["media"]:
        try:
            media = json.loads(row["media"])
        except (ValueError, TypeError):
            media = None
    rec: dict[str, Any] = {
        "id_str": row["id_str"],
        "member": row["member"],
        "member_name": row["member_name"],
        "created_at": row["created_at"],
        "text": row["text"],
        "text_id": row["text_id"],
        "favorite_count": row["favorite_count"] or 0,
        "conversation_count": row["conversation_count"] or 0,
        "url": row["url"],
    }
    if media:
        rec["media"] = media
    return rec


def _atomic_write(path: Path, text: str) -> bool:
    """Tulis atomik. Kembalikan True bila isi berubah (perlu di-commit)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == text:
                return False
        except OSError:
            pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return True


def export_all(conn: sqlite3.Connection, out_dir: str | Path) -> dict[str, Any]:
    """Ekspor seluruh isi DB ke `out_dir`. Aman dipanggil berulang."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    rows = conn.execute(
        "SELECT * FROM tweets ORDER BY created_at ASC, id_str ASC"
    ).fetchall()

    # --- kelompokkan per bulan
    months: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        months.setdefault(str(r["created_at"])[:7], []).append(r)

    months_manifest: list[dict[str, Any]] = []
    changed = 0
    for month in sorted(months):
        recs = [record_from_row(r) for r in months[month]]
        body = "".join(json.dumps(rec, ensure_ascii=False) + "\n" for rec in recs)
        rel = f"tweets/{month}.jsonl"
        if _atomic_write(out / rel, body):
            changed += 1
        months_manifest.append({
            "month": month,
            "file": rel,
            "count": len(recs),
            "translated": sum(1 for r in recs if r.get("text_id")),
        })

    # --- members.json (bentuk sama dengan /api/members)
    counts = {
        r["member"]: r for r in conn.execute(
            "SELECT member, COUNT(*) AS n, MAX(avatar) AS avatar, MAX(created_at) AS last_at "
            "FROM tweets GROUP BY member"
        ).fetchall()
    }
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for screen in MEMBERS:
        info = member_info(screen)
        c = counts.get(screen)
        members.append({
            **info,
            "count": c["n"] if c else 0,
            "avatar": c["avatar"] if c else None,
            "last_at": c["last_at"] if c else None,
        })
        seen.add(screen)
    for screen, c in counts.items():
        if screen not in seen:
            members.append({**member_info(screen), "count": c["n"],
                            "avatar": c["avatar"], "last_at": c["last_at"]})
    members.sort(key=lambda m: -m["count"])
    changed += _atomic_write(out / "members.json",
                             json.dumps(members, ensure_ascii=False, indent=1) + "\n")

    # --- stats.json + index.json
    st = dbm.stats(conn)
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stats_doc = {**st, "generated_at": generated_at,
                 "source": "https://gsm-app.com/lovelive/ikizulive-x-archive/"}
    changed += _atomic_write(out / "stats.json",
                             json.dumps(stats_doc, ensure_ascii=False, indent=1) + "\n")

    index_doc = {
        "generated_at": generated_at,
        "total": st["total"],
        "translated": st["translated"],
        "months": months_manifest,
    }
    changed += _atomic_write(out / "index.json",
                             json.dumps(index_doc, ensure_ascii=False, indent=1) + "\n")

    return {
        "out_dir": str(out),
        "tweets": len(rows),
        "months": len(months_manifest),
        "translated": st["translated"],
        "files_changed": changed,
        "generated_at": generated_at,
    }


def open_readonly(db_path: str) -> sqlite3.Connection:
    """Koneksi baca-saja (untuk CLI di host saat DB dimiliki user lain)."""
    conn = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def connect_for_export(db_path: str) -> sqlite3.Connection:
    """Coba koneksi normal; kalau DB tidak bisa ditulis, pakai mode baca-saja."""
    try:
        conn = dbm.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL").fetchall()
        return conn
    except sqlite3.OperationalError:
        return open_readonly(db_path)


def default_out_dir() -> str:
    """dataset/ di root repo (backend/ → naik satu level)."""
    return str(Path(__file__).resolve().parent.parent.parent / "dataset")


__all__ = ["EXPORT_FIELDS", "record_from_row", "export_all", "connect_for_export", "open_readonly"]
