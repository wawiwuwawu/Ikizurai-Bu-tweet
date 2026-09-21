"""REST API untuk frontend (dan konsumen lain).

Koneksi SQLite dibuka per-request (thread-safe; worker punya koneksi sendiri).
"""
from __future__ import annotations

import json
from typing import Any, Iterator, Optional

from fastapi import APIRouter, Depends, Query, Request

from . import db as dbm
from .members import MEMBERS, member_info

router = APIRouter()


def get_conn(request: Request) -> Iterator[Any]:
    conn = dbm.connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def _row_to_tweet(row: Any) -> dict[str, Any]:
    media = None
    if row["media"]:
        try:
            media = json.loads(row["media"])
        except (ValueError, TypeError):
            media = None
    return {
        "id_str": row["id_str"],
        "member": row["member"],
        "member_name": row["member_name"],
        "avatar": row["avatar"],
        "created_at": row["created_at"],
        "text": row["text"],
        "text_id": row["text_id"],
        "favorite_count": row["favorite_count"],
        "conversation_count": row["conversation_count"],
        "is_reply": bool(row["is_reply"]),
        "media": media,
        "url": row["url"],
    }


@router.get("/healthz")
def healthz(conn: Any = Depends(get_conn)) -> dict[str, Any]:
    return {"status": "ok", "db": "sqlite", "total": dbm.stats(conn)["total"]}


@router.get("/api/stats")
def api_stats(conn: Any = Depends(get_conn)) -> dict[str, Any]:
    return dbm.stats(conn)


@router.get("/api/members")
def api_members(conn: Any = Depends(get_conn)) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT member, COUNT(*) AS n, MAX(avatar) AS avatar, MAX(created_at) AS last_at "
        "FROM tweets GROUP BY member"
    ).fetchall()
    counts = {r["member"]: r for r in rows}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for screen in MEMBERS:
        info = member_info(screen)
        r = counts.get(screen)
        out.append({
            **info,
            "count": r["n"] if r else 0,
            "avatar": (r["avatar"] if r else None),
            "last_at": (r["last_at"] if r else None),
        })
        seen.add(screen)
    # member tak dikenal di data (jaga-jaga) tetap tampil
    for screen, r in counts.items():
        if screen not in seen:
            out.append({**member_info(screen), "count": r["n"], "avatar": r["avatar"], "last_at": r["last_at"]})
    out.sort(key=lambda m: -m["count"])
    return out


@router.get("/api/tweets")
def api_tweets(
    conn: Any = Depends(get_conn),
    member: Optional[str] = Query(None, description="screen_name member"),
    q: Optional[str] = Query(None, description="cari di teks JP & ID"),
    since: Optional[str] = Query(None, description="YYYY-MM-DD (inklusif)"),
    until: Optional[str] = Query(None, description="YYYY-MM-DD (inklusif)"),
    before: Optional[str] = Query(None, description="kursor id_str (eksklusif)"),
    limit: int = Query(30, ge=1, le=100),
) -> dict[str, Any]:
    rows, next_before = dbm.query_tweets(
        conn, member=member, q=q, since=since, until=until, before=before, limit=limit
    )
    return {"items": [_row_to_tweet(r) for r in rows], "next_before": next_before}
