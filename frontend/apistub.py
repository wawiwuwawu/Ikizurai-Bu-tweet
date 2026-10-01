"""Jalankan query_tweets backend (SQL asli) tanpa FastAPI/dotenv, untuk uji frontend.
Server stdlib_only di :8099 — endpoint /api/tweets, /api/members, /api/stats sama
seperti app/api.py, memakai SQL yang sama persis dengan app/db.query_tweets.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

DB = sys.argv[1] if len(sys.argv) > 1 else "/tmp/api-test.db"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8099
DATASET_DIR = Path(__file__).resolve().parents[1] / "dataset"
MEMBERS = json.loads((DATASET_DIR / "members.json").read_text(encoding="utf-8"))


def connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def query_tweets(conn, *, member=None, q=None, since=None, until=None,
                 before=None, after=None, limit=30, order="desc"):
    """Salinan PERSIS dari backend/app/db.py::query_tweets."""
    asc = str(order).lower() == "asc"
    where, args = [], []
    if member:
        where.append("member = ?"); args.append(member)
    if q:
        where.append("(text LIKE ? OR text_id LIKE ?)")
        like = f"%{q}%"; args.extend([like, like])
    if since:
        where.append("created_at >= ?"); args.append(since)
    if until:
        where.append("created_at <= ?")
        args.append(until + "T23:59:59Z" if len(until) == 10 else until)
    cursor = after if asc else before
    if cursor:
        if asc:
            where.append("(created_at > (SELECT created_at FROM tweets WHERE id_str = ?) "
                         "OR (created_at = (SELECT created_at FROM tweets WHERE id_str = ?) AND id_str > ?))")
        else:
            where.append("(created_at < (SELECT created_at FROM tweets WHERE id_str = ?) "
                         "OR (created_at = (SELECT created_at FROM tweets WHERE id_str = ?) AND id_str < ?))")
        args.extend([cursor, cursor, cursor])
    sql = "SELECT * FROM tweets"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at ASC, id_str ASC LIMIT ?" if asc else " ORDER BY created_at DESC, id_str DESC LIMIT ?"
    args.append(limit + 1)
    rows = conn.execute(sql, args).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = rows[-1]["id_str"] if (has_more and rows) else None
    return rows, next_cursor


def row_to_tweet(r):
    media = None
    if r["media"]:
        try:
            media = json.loads(r["media"])
        except (ValueError, TypeError):
            media = None
    return {"id_str": r["id_str"], "member": r["member"], "member_name": r["member_name"],
            "avatar": r["avatar"], "created_at": r["created_at"], "text": r["text"],
            "text_id": r["text_id"], "favorite_count": r["favorite_count"],
            "conversation_count": r["conversation_count"], "is_reply": bool(r["is_reply"]),
            "media": media, "url": r["url"]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        conn = connect()
        try:
            if u.path == "/api/tweets":
                rows, nxt = query_tweets(
                    conn, member=q.get("member"), q=q.get("q"), since=q.get("since"),
                    until=q.get("until"), before=q.get("before"), after=q.get("after"),
                    limit=int(q.get("limit", 30)), order=q.get("order", "desc"))
                order = q.get("order", "desc")
                self._send({"items": [row_to_tweet(r) for r in rows], "order": order, "next_cursor": nxt,
                            "next_before": nxt if order != "asc" else None,
                            "next_after": nxt if order == "asc" else None})
            elif u.path == "/api/members":
                rows = conn.execute("SELECT member, COUNT(*) AS n, MAX(avatar) AS avatar, MAX(created_at) AS last_at "
                                    "FROM tweets GROUP BY member").fetchall()
                counts = {r["member"]: r for r in rows}
                out = [{**m, "count": counts[m["screen_name"]]["n"] if m["screen_name"] in counts else 0,
                        "avatar": (counts[m["screen_name"]]["avatar"] if m["screen_name"] in counts else None),
                        "last_at": (counts[m["screen_name"]]["last_at"] if m["screen_name"] in counts else None)}
                       for m in MEMBERS if m["screen_name"] in counts]
                out.sort(key=lambda m: -m["count"])
                self._send(out)
            elif u.path == "/api/stats":
                one = lambda s: conn.execute(s).fetchone()[0]
                self._send({"total": one("SELECT COUNT(*) FROM tweets"),
                            "translated": one("SELECT COUNT(*) FROM tweets WHERE text_id IS NOT NULL"),
                            "notified": 0, "pending_notify": 0,
                            "oldest": one("SELECT MIN(created_at) FROM tweets"),
                            "newest": one("SELECT MAX(created_at) FROM tweets"),
                            "generated_at": None, "last_check": ""})
            else:
                self.send_response(404); self.end_headers()
        finally:
            conn.close()


def seed():
    conn = connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tweets (
            id_str TEXT PRIMARY KEY, member TEXT, member_name TEXT, avatar TEXT,
            created_at TEXT, text TEXT, text_id TEXT, favorite_count INTEGER DEFAULT 0,
            conversation_count INTEGER DEFAULT 0, is_reply INTEGER DEFAULT 0,
            media TEXT, quoted_tweet TEXT, url TEXT, raw TEXT,
            notify_state TEXT DEFAULT 'pending', notified_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_created ON tweets(created_at, id_str);
        CREATE INDEX IF NOT EXISTS idx_member ON tweets(member);
    """)
    rows = []
    tdir = DATASET_DIR / "tweets"
    for f in sorted(tdir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            media = r.get("media")
            rows.append((str(r["id_str"]), r["member"], r.get("member_name"), r.get("avatar"),
                         r["created_at"], r.get("text") or "", r.get("text_id"),
                         int(r.get("favorite_count") or 0), int(r.get("conversation_count") or 0),
                         1 if r.get("is_reply") else 0,
                         json.dumps(media) if media else None, None, r.get("url") or "", None))
    conn.executemany(
        "INSERT OR REPLACE INTO tweets (id_str,member,member_name,avatar,created_at,text,text_id,"
        "favorite_count,conversation_count,is_reply,media,quoted_tweet,url,raw) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM tweets").fetchone()[0]
    conn.close()
    print(f"seeded {n} tweet -> {DB}", flush=True)


if __name__ == "__main__":
    if "--seed-only" not in sys.argv:
        seed()
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        if args:
            HTTPServer(("127.0.0.1", PORT), H).serve_forever()
    else:
        seed()