"""Klien translasi JP→ID via gateway OpenAI-compatible (OmniRoute).

Konfigurasi final (teruji 2026-09-21, lihat research/atria_test_report.md):
- reasoning_effort = "none"  ← kunci: model reasoning kalau tidak dimatikan
  akan menghabiskan max_tokens untuk token berpikir → output kosong / timeout 504.
- batch 5 tweet, output JSON array, parser toleran.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Optional

import requests

log = logging.getLogger("ikizurai.translate")

SYSTEM_PROMPT = """Kamu penerjemah profesional Jepang→Indonesia untuk konten anime (Love Live! Bluebird / イキヅライブ！).
Terjemahkan tweet akun karakter (cewek SMA) ke bahasa Indonesia yang natural, hidup, dan santai seperti orang Indonesia asli menulis di media sosial. Pakai "aku/kamu", jangan kaku atau formal.
Aturan:
- SEMUA kata harus dalam bahasa Indonesia. Jangan ada kata Inggris tertinggal (kecuali nama merek, judul lagu/acara, atau istilah yang memang tidak punya padanan; tulis nama dalam romaji).
- Pertahankan semua emoji, kaomoji, tanda baca khas (！！、ーー、～), dan jeda baris kosong antar paragraf.
- Nama karakter ditulis romaji (contoh: 高橋ポルカ → Takahashi Polka). Hashtag Jepang dibiarkan apa adanya (contoh: #いきづらい部).
- Jangan tambahkan penjelasan, catatan penerjemah, atau furigana.
Contoh gaya:
- どうしよう → "Gimana ya…"
- ありえないでしょ、そんなの💢 → "Nggak mungkin lah, masa gitu💢"
- とりあえずおなか減ったかも → "Yang jelas, kayaknya aku laper"
Output HANYA JSON array: [{"id":"<id>","id_text":"<terjemahan>"}]"""


def build_messages(tweets: list[dict[str, Any]]) -> list[dict[str, str]]:
    user_content = "\n".join(
        json.dumps({"id": t["id_str"], "text": t["text"]}, ensure_ascii=False) for t in tweets
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def parse_batch_json(content: str, expected_ids: list[str]) -> dict[str, str]:
    """Parser toleran: strip markdown fence, ambil array JSON pertama-terakhir.

    Mengembalikan hanya pasangan id→terjemahan yang valid & id-nya dikenal.
    """
    if not content:
        return {}
    s = content.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    i, j = s.find("["), s.rfind("]")
    if i == -1 or j == -1:
        return {}
    try:
        arr = json.loads(s[i:j + 1])
    except json.JSONDecodeError:
        return {}
    if not isinstance(arr, list):
        return {}
    known = set(expected_ids)
    out: dict[str, str] = {}
    for item in arr:
        if not isinstance(item, dict):
            continue
        _id = str(item.get("id") or item.get("id_str") or "").strip()
        txt = item.get("id_text") or item.get("text") or ""
        if _id in known and isinstance(txt, str) and txt.strip():
            out[_id] = txt.strip()
    return out


class TranslateError(Exception):
    """Error fatal yang tidak berguna di-retry cepat (kredensial/format request)."""


def translate_batch(
    session: requests.Session,
    *,
    base_url: str,
    api_key: str,
    model: str,
    tweets: list[dict[str, Any]],
    reasoning_effort: Optional[str] = None,
    max_tokens: int = 2500,
    temperature: float = 0.3,
    timeout: int = 120,
) -> tuple[dict[str, str], Optional[str]]:
    """1 percobaan translasi. Kembalikan (hasil, error_string|None)."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": build_messages(tweets),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort

    resp = session.post(
        f"{base_url}/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=timeout,
    )
    if resp.status_code in (401, 403):
        raise TranslateError(f"HTTP {resp.status_code}: kredensial gateway ditolak")
    if resp.status_code >= 400:
        return {}, f"HTTP {resp.status_code}: {resp.text[:180]}"

    try:
        data = resp.json()
    except ValueError:
        return {}, f"respons bukan JSON: {resp.text[:180]}"

    choices = data.get("choices") or []
    if not choices:
        err = data.get("error") or data
        return {}, f"tanpa choices: {str(err)[:180]}"

    content = (choices[0].get("message") or {}).get("content") or ""
    finish = choices[0].get("finish_reason")
    parsed = parse_batch_json(content, [t["id_str"] for t in tweets])
    if not parsed:
        return {}, f"parse gagal (finish={finish}, len={len(content)}): {content[:120]!r}"
    return parsed, None


def translate_with_retry(
    session: requests.Session,
    *,
    base_url: str,
    api_key: str,
    model: str,
    tweets: list[dict[str, Any]],
    reasoning_effort: Optional[str] = None,
    max_tokens: int = 2500,
    attempts: int = 3,
    base_delay: float = 5.0,
    max_delay: float = 60.0,
    sleep=time.sleep,
) -> tuple[dict[str, str], Optional[str]]:
    """Beberapa percobaan dengan backoff eksponensial + jitter kecil."""
    last_err: Optional[str] = None
    for i in range(attempts):
        try:
            result, err = translate_batch(
                session, base_url=base_url, api_key=api_key, model=model, tweets=tweets,
                reasoning_effort=reasoning_effort, max_tokens=max_tokens,
            )
        except TranslateError:
            raise
        except requests.RequestException as e:
            result, err = {}, f"koneksi: {e}"
        if result:
            return result, None
        last_err = err
        if i < attempts - 1:
            delay = min(base_delay * (2 ** i), max_delay)
            log.warning("translate gagal (percobaan %d/%d): %s — tunggu %.0fs", i + 1, attempts, err, delay)
            sleep(delay)
    return {}, last_err


def clean_retry_backoff(attempts_done: int, base: int, cap: int) -> int:
    """Backoff antar-siklus (disimpan di DB lewat next_retry_at)."""
    return int(min(base * (2 ** max(0, attempts_done - 1)), cap))
