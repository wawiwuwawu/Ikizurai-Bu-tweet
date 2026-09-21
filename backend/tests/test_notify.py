"""Tes notifier Discord: format embed (sesuai permintaan user), waktu, kirim."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.notify import (  # noqa: E402
    RateLimiter, build_embed, build_payload, collapse_newlines, format_wib, send_payload,
)

ROW = {
    "id_str": "1900531357174128835",
    "member": "polka_lion",
    "member_name": "高橋ポルカ@いきづらい部！",
    "avatar": "https://pbs.twimg.com/profile_images/1921886430265221121/uOWsSYJW_400x400.png",
    "created_at": "2025-03-14T12:56:00.000Z",
    "text": "どうしよう\n\n高校落ちた\n\nどうしようどうしようどうしよう",
    "text_id": "Gimana ya…\n\nAku nggak keterima SMA\n\nGimana ya gimana ya gimana ya",
    "favorite_count": 2090,
    "conversation_count": 46,
    "url": "https://x.com/polka_lion/status/1900531357174128835",
    "media": None,
}


def test_format_wib():
    assert format_wib("2025-03-14T12:56:00.000Z") == "14/03/2025 7:56 PM"
    assert format_wib("2026-09-18T12:25:00.000Z") == "18/09/2026 7:25 PM"
    assert format_wib("2025-01-01T00:05:00.000Z") == "01/01/2025 7:05 AM"  # tengah malam WIB


def test_collapse_newlines():
    assert collapse_newlines("a\n\n\n\n\nb") == "a\n\nb"
    assert collapse_newlines("a  \nb") == "a\nb"
    assert collapse_newlines("  x  ") == "x"


def test_build_embed_format_sesuai_permintaan():
    e = build_embed(ROW)
    assert e["author"]["name"] == "高橋ポルカ · @polka_lion"
    assert e["author"]["url"] == ROW["url"]
    assert e["author"]["icon_url"].endswith("_400x400.png")
    assert e["title"] == "Tweet baru dari 高橋ポルカ (Takahashi Polka)"
    assert e["url"] == ROW["url"]
    assert "どうしよう" in e["description"]
    assert "━━━━━━━━━━━━━━" in e["description"]
    assert "🇮🇩 Terjemahan:" in e["description"]
    assert e["description"].index("どうしよう") < e["description"].index("Gimana ya")
    assert e["footer"]["text"] == "IkizuLive X Archive • 14/03/2025 7:56 PM"
    assert isinstance(e["color"], int) and 0 <= e["color"] <= 0xFFFFFF


def test_build_embed_tanpa_terjemahan():
    row = {**ROW, "text_id": None}
    e = build_embed(row)
    assert "🇮🇩 Terjemahan" not in e["description"]
    assert "どうしよう" in e["description"]


def test_build_embed_deskripsi_dipotong_di_4096():
    row = {**ROW, "text": "あ" * 5000, "text_id": None}
    e = build_embed(row)
    assert len(e["description"]) <= 4096


def test_build_embed_media_menjadi_image():
    row = {**ROW, "media": json.dumps(["https://pbs.twimg.com/media/ABC123.jpg"])}
    e = build_embed(row)
    assert e["image"]["url"].startswith("https://pbs.twimg.com/media/ABC123.jpg")


def test_payload_wajib_allowed_mentions_kosong():
    p = build_payload(ROW)
    assert p["allowed_mentions"] == {"parse": []}
    assert len(p["embeds"]) == 1


class FakeResp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload or {})

    def json(self):
        return self._payload or {}


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json})
        return self.responses.pop(0)


def test_send_payload_sukses_204():
    s = FakeSession([FakeResp(204)])
    ok, info = send_payload(s, "https://discord.com/api/webhooks/x/y", build_payload(ROW),
                            limiter=RateLimiter(sleep=lambda *_: None), sleep=lambda *_: None)
    assert ok and info == ""
    assert "wait=true" in s.calls[0]["url"]


def test_send_payload_429_lalu_sukses():
    s = FakeSession([FakeResp(429, {"retry_after": 0.1, "global": False}), FakeResp(200, {"id": "123"})])
    slept = []
    ok, info = send_payload(s, "https://discord.com/api/webhooks/x/y", build_payload(ROW),
                            limiter=RateLimiter(sleep=slept.append), sleep=slept.append)
    assert ok and info == "123"
    assert any(w >= 0.1 for w in slept)


def test_send_payload_404_fatal_tanpa_retry():
    s = FakeSession([FakeResp(404, {"message": "Unknown Webhook"})])
    ok, info = send_payload(s, "https://discord.com/api/webhooks/x/y", build_payload(ROW),
                            limiter=RateLimiter(sleep=lambda *_: None), sleep=lambda *_: None)
    assert not ok and info.startswith("FATAL 404")
    assert len(s.calls) == 1  # tidak retry


def test_send_payload_dry_run_tidak_mengirim():
    s = FakeSession([])
    ok, info = send_payload(s, "https://discord.com/api/webhooks/x/y", build_payload(ROW), dry_run=True)
    assert ok and info == "dry-run" and s.calls == []


def test_rate_limiter_menghormati_window():
    slept = []
    rl = RateLimiter(per_minute=2, min_interval=0, sleep=slept.append)
    rl.mark_sent(); rl.mark_sent()          # 2 pesan terkirim < 60s
    rl.preflight()                           # ke-3 → harus menunggu
    assert slept and slept[0] > 0
