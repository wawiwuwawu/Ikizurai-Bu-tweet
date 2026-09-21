"""Smoke test HTTP nyata: jalankan uvicorn di thread terpisah lalu curl endpoint.

Menangkap bug kelas "thread affinity" yang tidak terdeteksi TestClient
(TestClient menjalankan semuanya di satu thread).

Dilewati otomatis kalau uvicorn/requests tidak tersedia.
"""
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

requests = pytest.importorskip("requests")
uvicorn = pytest.importorskip("uvicorn")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).parent / "fixtures"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def live_server(tmp_path, monkeypatch):
    db_path = str(tmp_path / "live.db")
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("WORKER_ENABLED", "false")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/t")
    monkeypatch.setenv("OMNIROUTE_API_KEY", "k")

    from app import db as dbm
    from app.source import parse_tweet

    conn = dbm.connect(db_path)
    dbm.init_db(conn)
    raw = json.loads((FIXTURES / "sample_tweets.json").read_text())
    dbm.upsert_tweets(conn, [parse_tweet(t) for t in raw])
    conn.close()

    from app.main import create_app

    port = _free_port()
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()

    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            requests.get(base + "/healthz", timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.05)
    else:
        pytest.fail("server tidak siap")

    yield base
    server.should_exit = True
    t.join(timeout=5)


def test_endpoint_nyata_multi_thread(live_server):
    # panggil beruntun beberapa endpoint — masing-masing di threadpool thread berbeda
    for _ in range(6):
        r = requests.get(live_server + "/api/stats", timeout=5)
        assert r.status_code == 200, r.text
        r = requests.get(live_server + "/api/members", timeout=5)
        assert r.status_code == 200, r.text
        r = requests.get(live_server + "/api/tweets", params={"limit": 2}, timeout=5)
        assert r.status_code == 200, r.text
        assert len(r.json()["items"]) == 2
