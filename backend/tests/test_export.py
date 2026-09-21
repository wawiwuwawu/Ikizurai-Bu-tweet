"""Tes ekspor dataset publik: struktur, idempoten, atomik, manifest."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db as dbm  # noqa: E402
from app import export as ex  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def conn(tmp_path):
    c = dbm.connect(str(tmp_path / "test.db"))
    dbm.init_db(c)
    yield c
    c.close()


def _items():
    from app.source import parse_tweet

    raw = json.loads((FIXTURES / "sample_tweets.json").read_text())
    return [parse_tweet(t) for t in raw]


@pytest.fixture()
def seeded(conn):
    dbm.upsert_tweets(conn, _items())
    return conn


def test_export_membuat_file_per_bulan(seeded, tmp_path):
    out = tmp_path / "dataset"
    result = ex.export_all(seeded, out)

    assert result["tweets"] == len(_items())
    assert result["months"] >= 1
    files = sorted(p.name for p in (out / "tweets").glob("*.jsonl"))
    assert len(files) == result["months"]
    for f in files:
        assert f.endswith(".jsonl") and len(f) == len("YYYY-MM.jsonl")


def test_export_idempoten(seeded, tmp_path):
    out = tmp_path / "dataset"
    first = ex.export_all(seeded, out)
    assert first["files_changed"] > 0
    second = ex.export_all(seeded, out)
    assert second["files_changed"] == 0        # tidak ada yang berubah → git tetap bersih


def test_export_tidak_meninggalkan_tmp(seeded, tmp_path):
    out = tmp_path / "dataset"
    ex.export_all(seeded, out)
    assert list(out.rglob("*.tmp")) == []


def test_export_baris_json_valid_dan_urut(seeded, tmp_path):
    out = tmp_path / "dataset"
    ex.export_all(seeded, out)
    for f in sorted((out / "tweets").glob("*.jsonl")):
        recs = [json.loads(line) for line in f.read_text().splitlines() if line.strip()]
        assert recs, f"{f} kosong"
        keys = [(r["created_at"], r["id_str"]) for r in recs]
        assert keys == sorted(keys)            # urut naik, stabil
        for r in recs:
            assert r["id_str"] and r["text"] and r["url"]
            assert r["created_at"][:7] == f.stem


def test_export_text_id_kosong_untuk_belum_diterjemahkan(seeded, tmp_path):
    out = tmp_path / "dataset"
    ex.export_all(seeded, out)
    total = translated = 0
    for f in (out / "tweets").glob("*.jsonl"):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            total += 1
            assert rec["text_id"] is None  # belum ada translasi
            translated += 1 if rec["text_id"] else 0
    assert total == len(_items()) and translated == 0


def test_export_index_dan_members(seeded, tmp_path):
    out = tmp_path / "dataset"
    ex.export_all(seeded, out)

    index = json.loads((out / "index.json").read_text())
    assert index["total"] == len(_items())
    assert sum(m["count"] for m in index["months"]) == index["total"]
    for m in index["months"]:
        assert (out / m["file"]).exists()

    members = json.loads((out / "members.json").read_text())
    assert len(members) >= 1
    for m in members:
        assert {"screen_name", "jp_name", "romaji", "color", "count"} <= set(m)
        assert m["color"].startswith("#")

    stats = json.loads((out / "stats.json").read_text())
    assert stats["total"] == index["total"] and stats["generated_at"]


def test_export_menghitung_translasi(seeded, tmp_path):
    # tandai satu tweet sebagai sudah diterjemahkan
    row = seeded.execute("SELECT id_str FROM tweets LIMIT 1").fetchone()
    seeded.execute("UPDATE tweets SET text_id = 'Halo dunia' WHERE id_str = ?", (row["id_str"],))
    seeded.commit()

    out = tmp_path / "dataset"
    result = ex.export_all(seeded, out)
    assert result["translated"] == 1

    index = json.loads((out / "index.json").read_text())
    assert index["translated"] == 1
    month = next(m for m in index["months"] if True)
    assert (out / month["file"]).exists()

    found = False
    for f in (out / "tweets").glob("*.jsonl"):
        for line in f.read_text().splitlines():
            if line.strip() and json.loads(line)["id_str"] == row["id_str"]:
                assert json.loads(line)["text_id"] == "Halo dunia"
                found = True
    assert found
