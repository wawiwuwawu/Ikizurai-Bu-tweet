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

SYSTEM_PROMPT = """Kamu penulis/editor untuk akun karakter Love Live! Bluebird (イキヅライブ！), 10 cewek SMA yang nge-tweet di X.
Tulis ulang tweet Jepang berikut jadi bahasa Indonesia yang terdengar seperti tulisan cewek SMA Indonesia di X/Twitter.
Bukan terjemahan kata per kata — tulis ulang MAKSUDNYA dengan gaya bahasa dia sendiri.

Aturan:
- Urutan kata bebas kamu ubah supaya enak dibaca. JANGAN ikuti struktur kalimat Jepang.
- Boleh campur kata Inggris yang wajar dipakai anak muda Indonesia di medsos (happy, all out, literally, the best, nice, dst). Jangan dipaksa jadi Indonesia kalau malah kaku.
- Kata yang boleh dipakai: aku, nggak/gak, udah, banget, nih, deh, dong, sih, yuk, kayak, emang, bakal, mah, gitu.
- Istilah Jepang yang lazim tetap: senpai, bunkasai, omamori, matsuri, -chan/-san.
- Hashtag Jepang dibiarkan. Emoji, kaomoji, tanda ！！！ ーー ～, dan baris kosong dipertahankan.
- Kapitalisasi normal (awal kalimat huruf kapital). Jangan menambah penjelasan/catatan.

Nama karakter WAJIB dieja persis begini (jangan salah ketik):
Polka, Mai, Akira, Hanabi, Miracle, Noriko, Yukuri, Aurora, Midori, Shion.
Contoh: 高橋ポルカ → Takahashi Polka ・ 佐々木翔音 → Sasaki Shion ・ 此花輝夜 → Konohana Aurora

Glosarium konsisten:
- いきづらい部 → "Ikizurai-bu" ・ 文化祭 → "bunkasai" ・ 総リハ → "gladi resik" ・ ありがとう → "makasih" ・ ライブ → "live"

Frasa yang sering salah — terjemahkan begini:
- 全身全霊全力全開 → "all out!!!" (jangan panjang-panjang)
- なんて思ったりします → "ya kayak gitu deh, kira-kira"
- 〜かもしれないな → "kayaknya sih"
- お楽しみに → "tungguin ya"

Contoh perbaikan (JANGAN tiru yang kiri):
- "aku bakal lakukan apa pun yang bisa aku lakukan demi promosi itu" → "apa aja yang bisa aku lakuin buat promosinya, bakal aku lakuin"
- "Sebagai gantinya aku bakal semangat di panggungnya" → "Makanya aku bakal all out di panggung nanti"
- "Besok latihan menyeluruh" → "Besok gladi resik"
- "Terbaik banget" → "The best banget"

Sebelum menulis hasil akhir, baca ulang: kalau ada kata yang terdengar seperti buku pelajaran/berita (segenap, sekujur, merupakan, demi, hingga), ganti dengan bahasa santai.

Format keluaran: HANYA JSON array [{"id":"<id>","id_text":"<terjemahan>"}]"""


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

    Ada dua lapis:
    1. `json.loads` penuh (kasus normal).
    2. **Salvage**: kalau JSON terpotong/rusak (model berhenti di tengah), ambil
       objek-objek yang *lengkap* dengan regex — sisanya di-retry terpisah.
    Mengembalikan hanya pasangan id→terjemahan yang valid & id-nya dikenal.
    """
    if not content:
        return {}
    s = content.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]

    known = set(expected_ids)
    out: dict[str, str] = {}

    def _collect(arr) -> None:
        if not isinstance(arr, list):
            return
        for item in arr:
            if not isinstance(item, dict):
                continue
            _id = str(item.get("id") or item.get("id_str") or "").strip()
            txt = item.get("id_text") or item.get("text") or ""
            if _id in known and isinstance(txt, str) and txt.strip():
                out[_id] = txt.strip()

    i, j = s.find("["), s.rfind("]")
    if i != -1 and j != -1:
        try:
            _collect(json.loads(s[i:j + 1]))
        except json.JSONDecodeError:
            pass
    if len(out) == len(known):
        return out

    # Salvage: ambil objek lengkap satu per satu ({"id": "...", "id_text": "..."})
    for m in re.finditer(
        r'\{\s*"id"\s*:\s*"(?P<id>\d+)"\s*,\s*"id_text"\s*:\s*"(?P<text>(?:[^"\\]|\\.)*)"\s*\}',
        s,
    ):
        try:
            text = json.loads(f'"{m.group("text")}"')
        except json.JSONDecodeError:
            continue
        _id = m.group("id")
        if _id in known and text.strip():
            out.setdefault(_id, text.strip())
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
    temperature: float = 0.5,
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
