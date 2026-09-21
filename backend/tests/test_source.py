"""Tes klien sumber (gsm-app API): parameter, pagination, normalisasi."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.source import PAGE_SIZE, fetch_page, paginate, parse_tweet  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        return FakeResp(self.pages.pop(0))


def _tweet(i, text="hello"):
    return {"id_str": str(i), "text": text, "created_at": "2025-03-14T12:56:00.000Z",
            "user": {"screen_name": "polka_lion", "name": "高橋ポルカ@いきづらい部！"}}


def test_fetch_page_mengirim_semua_param():
    s = FakeSession([[{"id_str": "1"}]])
    fetch_page(s, "https://x.test/base", since="2025-01-01", until="2025-02-01",
               q="halo", from_="polka_lion", token="99", cache_bust=True)
    p = s.calls[0]["params"]
    assert p["since"] == "2025-01-01" and p["until"] == "2025-02-01"
    assert p["q"] == "halo" and p["from"] == "polka_lion"
    assert p["pagination_token"] == "99" and "_" in p  # cache-buster
    assert s.calls[0]["url"] == "https://x.test/base/api/x/posts"


def test_paginate_berhenti_saat_halaman_pendek():
    page_full = [_tweet(i) for i in range(PAGE_SIZE)]
    page_short = [_tweet(100 + i) for i in range(5)]
    s = FakeSession([page_full, page_short])
    pages = list(paginate(s, "https://x.test/base", delay=0))
    assert len(pages) == 2
    assert s.calls[1]["params"]["pagination_token"] == str(PAGE_SIZE - 1)


def test_paginate_berhenti_saat_kosong():
    s = FakeSession([[]])
    assert list(paginate(s, "https://x.test/base", delay=0)) == []


def test_parse_tweet_normalisasi():
    raw = json.loads((FIXTURES / "sample_tweets.json").read_text())
    t = parse_tweet(raw[0])
    assert t["id_str"] == "1900531357174128835"
    assert t["member"] == "polka_lion"
    assert t["member_name"].startswith("高橋ポルカ")
    assert t["avatar"].endswith("_400x400.png")
    assert t["url"].endswith("/status/1900531357174128835")
    assert t["is_reply"] is False
    assert t["media"] is None


def test_parse_tweet_dengan_media():
    raw = json.loads((FIXTURES / "sample_tweets.json").read_text())
    media_tweet = next(t for t in raw if t["id_str"] == "2003012758007423271")
    t = parse_tweet(media_tweet)
    assert t["media"] == ["https://pbs.twimg.com/media/G8wY1l-bwAAMPp1.jpg"]
