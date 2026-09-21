"""Tes integrasi worker: memastikan thread worker bisa memakai koneksinya sendiri.

Regresi: koneksi SQLite dibuat di main thread → dipakai di thread worker
→ `sqlite3.ProgrammingError` (thread affinity). Tes ini gagal kalau bug itu kembali.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_worker_thread_bisa_pakai_koneksinya(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "w.db"))
    monkeypatch.setenv("WORKER_ENABLED", "true")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1/t")
    monkeypatch.setenv("OMNIROUTE_API_KEY", "k")

    from app import db as dbm
    from app import worker as worker_mod

    results = []

    def fake_run_forever(self):
        # memakai self.conn (koneksi harus dibuat di thread yang sama)
        results.append(dbm.stats(self.conn)["total"])

    monkeypatch.setattr(worker_mod.Worker, "run_forever", fake_run_forever)

    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app()):
        for _ in range(50):
            if results:
                break
            time.sleep(0.05)

    assert results == [0], f"worker thread gagal memakai koneksi: {results!r}"
