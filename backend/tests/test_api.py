"""Tes API HTTP end-to-end (TestClient) — termasuk regresi bug threading SQLite."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "api.db")
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("WORKER_ENABLED", "false")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/test")
    monkeypatch.setenv("OMNIROUTE_API_KEY", "test-key")

    from app import db as dbm
    from app.source import parse_tweet

    conn = dbm.connect(db_path)
    dbm.init_db(conn)
    raw = json.loads((FIXTURES / "sample_tweets.json").read_text())
    items = [parse_tweet(t) for t in raw]
    dbm.upsert_tweets(conn, items)
    dbm.set_translated(conn, items[0]["id_str"], "terjemahan uji")
    conn.close()

    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["total"] == 3


def test_stats(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] == 3 and s["translated"] == 1


def test_members(client):
    r = client.get("/api/members")
    assert r.status_code == 200
    ms = r.json()
    assert len(ms) == 10                       # 10 member IkizuLive selalu tampil
    by = {m["screen_name"]: m for m in ms}
    assert by["polka_lion"]["count"] == 2
    assert by["polka_lion"]["jp_name"] == "高橋ポルカ"
    assert by["polka_lion"]["color"].startswith("#")


def test_tweets_default_dan_filter(client):
    r = client.get("/api/tweets", params={"limit": 10})
    assert r.status_code == 200
    d = r.json()
    assert len(d["items"]) == 3
    # urut terbaru dulu
    times = [t["created_at"] for t in d["items"]]
    assert times == sorted(times, reverse=True)

    r2 = client.get("/api/tweets", params={"member": "polka_lion"})
    assert all(t["member"] == "polka_lion" for t in r2.json()["items"])

    r3 = client.get("/api/tweets", params={"q": "terjemahan uji"})
    assert len(r3.json()["items"]) == 1


def test_tweets_pagination_kursor(client):
    d1 = client.get("/api/tweets", params={"limit": 1}).json()
    assert d1["next_before"]
    d2 = client.get("/api/tweets", params={"limit": 10, "before": d1["next_before"]}).json()
    assert all(t["id_str"] != d1["items"][0]["id_str"] for t in d2["items"])
