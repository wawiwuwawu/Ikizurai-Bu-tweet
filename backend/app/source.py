"""Sumber data: klien API arsip X (gsm-app.com).

Endpoint: GET {SOURCE_BASE}/api/x/posts
Param  : since, until (YYYY-MM-DD), q, from (screen_name), pagination_token (id_str)
Halaman: 30 tweet, urut lama → baru.
"""
from __future__ import annotations

import time
from typing import Any, Iterator, Optional

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
PAGE_SIZE = 30


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def fetch_page(
    session: requests.Session,
    base: str,
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
    q: Optional[str] = None,
    from_: Optional[str] = None,
    token: Optional[str] = None,
    cache_bust: bool = False,
    timeout: int = 20,
) -> list[dict[str, Any]]:
    """Ambil 1 halaman. cache_bust=True menambah ?_=<epoch> (untuk data segar)."""
    url = f"{base}/api/x/posts"
    params: dict[str, Any] = {}
    if since:
        params["since"] = since
    if until:
        params["until"] = until
    if q:
        params["q"] = q
    if from_:
        params["from"] = from_
    if token:
        params["pagination_token"] = token
    if cache_bust:
        params["_"] = int(time.time())

    resp = session.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict):
        raise RuntimeError(f"Respons API tidak terduga: {str(data)[:200]}")
    return data


def paginate(
    session: requests.Session,
    base: str,
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
    from_: Optional[str] = None,
    q: Optional[str] = None,
    cache_bust: bool = False,
    delay: float = 0.5,
    max_pages: int = 500,
) -> Iterator[list[dict[str, Any]]]:
    """Generator halaman demi halaman (lama → baru). Berhenti saat halaman < PAGE_SIZE."""
    token = None
    for _ in range(max_pages):
        page = fetch_page(
            session, base, since=since, until=until, from_=from_, q=q,
            token=token, cache_bust=cache_bust,
        )
        if not page:
            return
        yield page
        if len(page) < PAGE_SIZE:
            return
        token = page[-1]["id_str"]
        if delay:
            time.sleep(delay)


def parse_tweet(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalisasi 1 tweet dari API sumber → dict internal (konsisten)."""
    user = raw.get("user") or {}
    entities = raw.get("entities") or {}
    media = raw.get("mediaDetails") or raw.get("photos") or entities.get("media") or None

    media_urls: list[str] = []
    if isinstance(media, list):
        for m in media:
            if not isinstance(m, dict):
                continue
            u = m.get("media_url_https") or m.get("url")
            if u and str(u).startswith("http") and "twimg" in str(u):
                media_urls.append(str(u))

    screen = str(user.get("screen_name", "")).strip()
    avatar = ((user.get("profile_image_url_https") or "").strip() or None)
    if avatar:
        avatar = avatar.replace("_normal.", "_400x400.")
    return {
        "id_str": str(raw.get("id_str", "")).strip(),
        "member": screen,
        "member_name": (user.get("name") or "").strip() or None,
        "avatar": avatar,
        "created_at": raw.get("created_at"),
        "text": raw.get("text") or "",
        "favorite_count": int(raw.get("favorite_count") or 0),
        "conversation_count": int(raw.get("conversation_count") or 0),
        "is_reply": bool(raw.get("in_reply_to_status_id_str") or raw.get("in_reply_to_user_id_str")),
        "media": media_urls or None,
        "quoted_tweet": raw.get("quoted_tweet") or None,
        "url": f"https://x.com/{screen}/status/{raw.get('id_str')}" if screen else "",
        "raw": raw,
    }
