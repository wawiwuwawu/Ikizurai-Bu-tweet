"""Discord webhook notifier — fitur utama proyek.

Format embed (sesuai permintaan user):
  author  : "高橋ポルカ · @polka_lion"        (+ avatar ikon, link ke tweet)
  title   : "Tweet baru dari 高橋ポルカ (Takahashi Polka)"  (link ke tweet)
  desc    : teks JP  +  ━━━━━━━━━━━  +  "🇮🇩 Terjemahan:" + teks ID
  footer  : "IkizuLive X Archive • 14/03/2025 7:56 PM"
  color   : warna karakter member

Rate limit (dari riset resmi Discord):
- pagar keras 30 pesan/menit per webhook → sliding window.
- pace bucket dari header X-RateLimit-* (jangan hardcode).
- 429 → sleep `retry_after` (float detik) dari body; `global:true` → semua worker berhenti.
- 401/403/404 → JANGAN retry (budget invalid request → IP ban).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

from .members import hex_to_int, member_color, member_info

log = logging.getLogger("ikizurai.notify")

SEPARATOR = "━━━━━━━━━━━━━━"
FOOTER_PREFIX = "IkizuLive X Archive"

WIB = timezone(timedelta(hours=7))


# ---------------------------------------------------------------- rate limiter

class RateLimiter:
    """Sliding-window 30 pesan/menit + pace minimal antar request."""

    def __init__(self, per_minute: int = 30, min_interval: float = 0.4, sleep=time.sleep):
        self.per_minute = per_minute
        self.min_interval = min_interval
        self._sent: list[float] = []
        self._last = 0.0
        self._sleep = sleep
        self._retry_after = 0.0  # dipakai saat 429 global

    def preflight(self) -> None:
        now = time.time()
        wait = self._retry_after - now
        if wait > 0:
            self._sleep(wait)
            now = time.time()
        self._sent = [t for t in self._sent if now - t < 60]
        if len(self._sent) >= self.per_minute:
            self._sleep(60 - (now - self._sent[0]) + 0.5)
        gap = self.min_interval - (time.time() - self._last)
        if gap > 0:
            self._sleep(gap)

    def mark_sent(self) -> None:
        self._last = time.time()
        self._sent.append(self._last)

    def apply_headers(self, headers: Any) -> None:
        try:
            remaining = headers.get("X-RateLimit-Remaining")
            reset_after = headers.get("X-RateLimit-Reset-After")
            if remaining == "0" and reset_after:
                self._sleep(float(reset_after) + 0.05)
        except (TypeError, ValueError):
            pass

    def set_global_retry(self, seconds: float) -> None:
        self._retry_after = max(self._retry_after, time.time() + seconds)


# ---------------------------------------------------------------- formatting

def collapse_newlines(text: str) -> str:
    """3+ newline → 1 baris kosong; rapikan spasi di ujung baris."""
    import re

    text = (text or "").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return text


def format_wib(created_at: str) -> str:
    """'2025-03-14T12:56:00.000Z' → '14/03/2025 7:56 PM' (WIB, 12 jam)."""
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(WIB)
    except (ValueError, AttributeError):
        return created_at or ""
    hour = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt.day:02d}/{dt.month:02d}/{dt.year} {hour}:{dt.strftime('%M %p')}"


def avatar_of(row: dict[str, Any]) -> Optional[str]:
    """Ambil avatar member (versi _400x400) dari kolom avatar / raw JSON."""
    avatar = row.get("avatar")
    if not avatar and row.get("raw"):
        try:
            raw = json.loads(row["raw"]) if isinstance(row["raw"], str) else row["raw"]
            avatar = ((raw.get("user") or {}).get("profile_image_url_https")) or None
        except (ValueError, AttributeError):
            avatar = None
    if avatar:
        return str(avatar).replace("_normal.", "_400x400.")
    return None


def build_embed(row: dict[str, Any]) -> dict[str, Any]:
    """Bangun embed sesuai format yang diminta user."""
    screen = row["member"]
    info = member_info(screen)
    avatar = avatar_of(row)
    url = row.get("url") or f"https://x.com/{screen}/status/{row['id_str']}"

    jp = collapse_newlines(row["text"])
    parts = [jp]
    if row.get("text_id"):
        parts.append(f"{SEPARATOR}\n🇮🇩 Terjemahan:\n{collapse_newlines(row['text_id'])}")
    description = "\n\n".join(parts)
    if len(description) > 4096:
        description = description[:4093] + "…"

    author: dict[str, Any] = {"name": f"{info['jp_name']} · @{screen}", "url": url}
    if avatar:
        author["icon_url"] = avatar

    embed: dict[str, Any] = {
        "author": author,
        "title": f"Tweet baru dari {info['jp_name']} ({info['romaji']})",
        "url": url,
        "description": description,
        "color": hex_to_int(member_color(screen)),
        "footer": {"text": f"{FOOTER_PREFIX} • {format_wib(row['created_at'])}"},
    }

    # media (jarang: 2 dari 2463 tweet)
    media = row.get("media")
    if media:
        try:
            urls = json.loads(media) if isinstance(media, str) else media
            if urls:
                first = str(urls[0])
                embed["image"] = {"url": first + (":large" if "pbs.twimg.com" in first and ":" not in first.split("/")[-1] else "")}
        except (ValueError, TypeError):
            pass
    return embed


def build_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "allowed_mentions": {"parse": []},
        "embeds": [build_embed(row)],
    }


# ---------------------------------------------------------------- sending

def send_payload(
    session: requests.Session,
    webhook_url: str,
    payload: dict[str, Any],
    *,
    limiter: Optional[RateLimiter] = None,
    max_attempts: int = 4,
    sleep=time.sleep,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """Kirim payload ke webhook. Kembalikan (sukses, info).

    info = message_id saat sukses, atau pesan error saat gagal.
    """
    if dry_run:
        log.info("[DRY_RUN] payload: %s", json.dumps(payload, ensure_ascii=False)[:400])
        return True, "dry-run"

    limiter = limiter or RateLimiter(sleep=sleep)
    url = webhook_url + ("&" if "?" in webhook_url else "?") + "wait=true"

    for attempt in range(max_attempts):
        limiter.preflight()
        try:
            resp = session.post(url, json=payload, timeout=20)
        except requests.RequestException as e:
            wait = min(2 ** attempt, 30) + 0.5
            log.warning("webhook koneksi error (%s), retry dalam %.1fs", e, wait)
            sleep(wait)
            continue

        limiter.mark_sent()
        limiter.apply_headers(resp.headers)

        if resp.status_code in (200, 204):
            mid = ""
            if resp.status_code == 200:
                try:
                    mid = str(resp.json().get("id", ""))
                except ValueError:
                    mid = ""
            return True, mid

        if resp.status_code == 429:
            try:
                body = resp.json()
                wait = float(body.get("retry_after", 1.0))
                if body.get("global"):
                    wait += 1.0
                    limiter.set_global_retry(wait)
            except (ValueError, TypeError):
                wait = float(resp.headers.get("Retry-After", 1) or 1)
            log.warning("webhook 429 — tunggu %.1fs", wait)
            sleep(wait + 0.1 * attempt)
            continue

        if resp.status_code in (401, 403, 404):
            return False, f"FATAL {resp.status_code} (tidak di-retry): {resp.text[:160]}"

        if 500 <= resp.status_code < 600:
            wait = min(2 ** attempt, 60) + 0.5
            log.warning("webhook %s — retry dalam %.1fs", resp.status_code, wait)
            sleep(wait)
            continue

        return False, f"HTTP {resp.status_code}: {resp.text[:160]}"

    return False, "gagal setelah beberapa percobaan"
