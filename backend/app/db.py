"""SQLite layer — skema + query. Semua fungsi menerima `conn` eksplisit (mudah dites).

Prinsip konsistensi:
- PK `id_str` → upsert idempoten, tidak ada duplikat.
- Kolom hasil kerja (text_id / notify_state) TIDAK pernah ditimpa oleh upsert.
- Semua waktu disimpan ISO-8601 UTC.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS tweets (
  id_str            TEXT PRIMARY KEY,
  member            TEXT NOT NULL,
  member_name       TEXT,
  avatar            TEXT,
  created_at        TEXT NOT NULL,
  text              TEXT NOT NULL,
  text_id           TEXT,
  translated_at     TEXT,
  translate_attempts INTEGER NOT NULL DEFAULT 0,
  next_retry_at     TEXT,
  favorite_count    INTEGER DEFAULT 0,
  conversation_count INTEGER DEFAULT 0,
  is_reply          INTEGER NOT NULL DEFAULT 0,
  media             TEXT,
  quoted_tweet      TEXT,
  url               TEXT NOT NULL,
  raw               TEXT,
  fetched_at        TEXT NOT NULL,
  notify_state      TEXT NOT NULL DEFAULT 'pending',
  notified_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_tweets_created    ON tweets(created_at DESC, id_str DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_member     ON tweets(member, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_translate  ON tweets(text_id, next_retry_at);
CREATE INDEX IF NOT EXISTS idx_tweets_notify     ON tweets(notify_state, created_at);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);
"""

# notify_state: 'pending' (menunggu kirim) | 'skipped' (baseline / tidak dikirim) | 'sent'


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: str) -> sqlite3.Connection:
    """Buka koneksi SQLite.

    check_same_thread=False: FastAPI menjalankan endpoint sync di threadpool —
    thread pembuat koneksi dan pemakainya bisa berbeda (dipakai bergantian,
    tidak bersamaan). SQLite + WAL + busy_timeout menangani serialisasi.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# ---------------------------------------------------------------- meta

def get_meta(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


# ---------------------------------------------------------------- tweets

UPDATABLE = ("text", "favorite_count", "conversation_count", "raw", "fetched_at", "media",
             "quoted_tweet", "member_name")


def upsert_tweets(conn: sqlite3.Connection, items: Iterable[dict[str, Any]]) -> list[str]:
    """Insert tweet baru / update field yang boleh berubah.

    Mengembalikan daftar id_str yang BARU (belum ada di DB).
    """
    new_ids: list[str] = []
    fetched = now_utc()
    for t in items:
        exists = conn.execute(
            "SELECT 1 FROM tweets WHERE id_str = ?", (t["id_str"],)
        ).fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO tweets
                   (id_str, member, member_name, avatar, created_at, text, favorite_count,
                    conversation_count, is_reply, media, quoted_tweet, url, raw, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    t["id_str"], t["member"], t.get("member_name"), t.get("avatar"), t["created_at"], t["text"],
                    t.get("favorite_count", 0), t.get("conversation_count", 0),
                    1 if t.get("is_reply") else 0,
                    json.dumps(t.get("media"), ensure_ascii=False) if t.get("media") else None,
                    json.dumps(t.get("quoted_tweet"), ensure_ascii=False) if t.get("quoted_tweet") else None,
                    t["url"], json.dumps(t.get("raw", {}), ensure_ascii=False), fetched,
                ),
            )
            new_ids.append(t["id_str"])
        else:
            conn.execute(
                """UPDATE tweets SET
                     text = ?, favorite_count = ?, conversation_count = ?,
                     raw = ?, fetched_at = ?, media = ?, quoted_tweet = ?, member_name = ?, avatar = ?
                   WHERE id_str = ?""",
                (
                    t["text"], t.get("favorite_count", 0), t.get("conversation_count", 0),
                    json.dumps(t.get("raw", {}), ensure_ascii=False), fetched,
                    json.dumps(t.get("media"), ensure_ascii=False) if t.get("media") else None,
                    json.dumps(t.get("quoted_tweet"), ensure_ascii=False) if t.get("quoted_tweet") else None,
                    t.get("member_name"), t.get("avatar"), t["id_str"],
                ),
            )
    conn.commit()
    return new_ids


def highest_id(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT MAX(id_str) AS m FROM tweets").fetchone()
    return row["m"] if row and row["m"] else None


def mark_skipped(conn: sqlite3.Connection, ids: Iterable[str]) -> int:
    ids = list(ids)
    if not ids:
        return 0
    cur = conn.executemany(
        "UPDATE tweets SET notify_state = 'skipped' WHERE id_str = ? AND notify_state = 'pending'",
        [(i,) for i in ids],
    )
    conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------- queue translasi

def translation_queue(conn: sqlite3.Connection, limit: int, max_attempts: int) -> list[sqlite3.Row]:
    """Tweet yang belum diterjemahkan.

    Prioritas: (1) yang menunggu notifikasi (notify_state='pending') lebih dulu,
    (2) lalu backfill — terbaru dulu. Hormati next_retry_at & max_attempts.
    """
    return conn.execute(
        """SELECT id_str, text, member, created_at FROM tweets
           WHERE text_id IS NULL
             AND translate_attempts < ?
             AND (next_retry_at IS NULL OR next_retry_at <= ?)
           ORDER BY (notify_state = 'pending') DESC, created_at DESC
           LIMIT ?""",
        (max_attempts, now_utc(), limit),
    ).fetchall()


def set_translated(conn: sqlite3.Connection, id_str: str, text_id: str) -> None:
    conn.execute(
        "UPDATE tweets SET text_id = ?, translated_at = ?, next_retry_at = NULL WHERE id_str = ?",
        (text_id, now_utc(), id_str),
    )
    conn.commit()


def mark_translate_failure(conn: sqlite3.Connection, id_str: str, backoff_seconds: int) -> int:
    """Naikkan attempts + jadwalkan retry berikutnya. Kembalikan attempts baru."""
    nxt = (datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "UPDATE tweets SET translate_attempts = translate_attempts + 1, next_retry_at = ? WHERE id_str = ?",
        (nxt, id_str),
    )
    conn.commit()
    row = conn.execute("SELECT translate_attempts FROM tweets WHERE id_str = ?", (id_str,)).fetchone()
    return row["translate_attempts"] if row else 0


# ---------------------------------------------------------------- queue notifikasi

def pending_notifications(conn: sqlite3.Connection, limit: int, require_translation: bool = True) -> list[sqlite3.Row]:
    cond = "AND text_id IS NOT NULL" if require_translation else ""
    return conn.execute(
        f"""SELECT id_str, member, member_name, created_at, text, text_id, favorite_count,
                   conversation_count, url, media, avatar, raw
            FROM tweets
            WHERE notify_state = 'pending' {cond}
            ORDER BY created_at ASC, id_str ASC
            LIMIT ?""",
        (limit,),
    ).fetchall()


def mark_notified(conn: sqlite3.Connection, id_str: str) -> None:
    conn.execute(
        "UPDATE tweets SET notify_state = 'sent', notified_at = ? WHERE id_str = ?",
        (now_utc(), id_str),
    )
    conn.commit()


# ---------------------------------------------------------------- API query

def query_tweets(
    conn: sqlite3.Connection,
    *,
    member: Optional[str] = None,
    q: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    before: Optional[str] = None,
    limit: int = 30,
) -> tuple[list[sqlite3.Row], Optional[str]]:
    """Ambil tweet terbaru dulu (untuk FE). `before` = id_str kursor (eksklusif).

    Kembalikan (rows, next_before). next_before = id_str baris terakhir bila masih ada.
    """
    where, args = [], []
    if member:
        where.append("member = ?")
        args.append(member)
    if q:
        where.append("(text LIKE ? OR text_id LIKE ?)")
        like = f"%{q}%"
        args.extend([like, like])
    if since:
        where.append("created_at >= ?")
        args.append(since)
    if until:
        where.append("created_at <= ?")
        args.append(until + "T23:59:59Z" if len(until) == 10 else until)
    if before:
        where.append("(created_at < (SELECT created_at FROM tweets WHERE id_str = ?) "
                     "OR (created_at = (SELECT created_at FROM tweets WHERE id_str = ?) AND id_str < ?))")
        args.extend([before, before, before])
    sql = "SELECT * FROM tweets"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, id_str DESC LIMIT ?"
    args.append(limit + 1)
    rows = conn.execute(sql, args).fetchall()
    next_before = rows[-1]["id_str"] if len(rows) > limit else None
    return rows[:limit], next_before


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    def one(sql: str, *args) -> int:
        return conn.execute(sql, args).fetchone()[0]

    return {
        "total": one("SELECT COUNT(*) FROM tweets"),
        "translated": one("SELECT COUNT(*) FROM tweets WHERE text_id IS NOT NULL"),
        "notified": one("SELECT COUNT(*) FROM tweets WHERE notify_state = 'sent'"),
        "pending_notify": one("SELECT COUNT(*) FROM tweets WHERE notify_state = 'pending'"),
        "oldest": one("SELECT COALESCE(MIN(created_at), '') FROM tweets"),
        "newest": one("SELECT COALESCE(MAX(created_at), '') FROM tweets"),
        "last_check": get_meta(conn, "last_check_utc", ""),
        "baseline_done": get_meta(conn, "baseline_done", "false"),
    }
