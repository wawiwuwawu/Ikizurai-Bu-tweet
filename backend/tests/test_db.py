"""Tes lapisan DB: idempoten, antrean, query, stats."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db as dbm  # noqa: E402

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


def test_upsert_idempotent(conn):
    items = _items()
    first = dbm.upsert_tweets(conn, items)
    assert len(first) == len(items)          # semua baru
    second = dbm.upsert_tweets(conn, items)
    assert second == []                       # ulang → tidak ada baru
    assert dbm.stats(conn)["total"] == len(items)


def test_upsert_tidak_menimpa_hasil_kerja(conn):
    items = _items()
    dbm.upsert_tweets(conn, items)
    iid = items[0]["id_str"]
    dbm.set_translated(conn, iid, "terjemahan contoh")
    dbm.mark_skipped(conn, [iid])
    # upsert ulang (mis. tweet di-like lagi di X)
    dbm.upsert_tweets(conn, items)
    row = conn.execute("SELECT text_id, notify_state FROM tweets WHERE id_str = ?", (iid,)).fetchone()
    assert row["text_id"] == "terjemahan contoh"   # tidak ditimpa
    assert row["notify_state"] == "skipped"        # tidak ditimpa


def test_parse_tweet_menormalkan_avatar_dan_url():
    items = _items()
    t = items[0]
    assert t["member"] == "polka_lion"
    assert t["avatar"].endswith("_400x400.png")    # _normal → _400x400
    assert t["url"] == f"https://x.com/polka_lion/status/{t['id_str']}"
    assert t["is_reply"] is False


def test_queue_translasi_prioritas_dan_retry(conn):
    items = _items()
    dbm.upsert_tweets(conn, items)
    ids = [i["id_str"] for i in items]
    dbm.mark_skipped(conn, ids[:1])  # satu skip → backfill
    # satu tweet dijadwalkan retry di masa depan → tidak keluar dari antrean
    dbm.mark_translate_failure(conn, ids[2], 3600)

    q = dbm.translation_queue(conn, 10, 5)
    qids = [r["id_str"] for r in q]
    assert ids[2] not in qids        # sedang backoff

    # prioritas: notify_state='pending' (ids[1]) sebelum backfill (ids[0])
    assert qids[0] == ids[1]

    # setelah next_retry_at lewat, muncul lagi
    conn.execute("UPDATE tweets SET next_retry_at = '2000-01-01T00:00:00Z' WHERE id_str = ?", (ids[2],))
    conn.commit()
    qids2 = [r["id_str"] for r in dbm.translation_queue(conn, 10, 5)]
    assert ids[2] in qids2


def test_max_attempts_menghentikan_antrean(conn):
    items = _items()
    dbm.upsert_tweets(conn, items)
    iid = items[0]["id_str"]
    conn.execute("UPDATE tweets SET translate_attempts = 5 WHERE id_str = ?", (iid,))
    conn.commit()
    qids = [r["id_str"] for r in dbm.translation_queue(conn, 10, 5)]
    assert iid not in qids


def test_notifikasi_hanya_setelah_terjemahan(conn):
    items = _items()
    dbm.upsert_tweets(conn, items)
    assert dbm.pending_notifications(conn, 10, require_translation=True) == []
    iid = items[0]["id_str"]
    dbm.set_translated(conn, iid, "halo")
    rows = dbm.pending_notifications(conn, 10, require_translation=True)
    assert [r["id_str"] for r in rows] == [iid]
    # avatar harus ikut terambil — dipakai untuk icon_url di embed Discord
    assert rows[0]["avatar"], "kolom avatar kosong di antrean notifikasi"
    assert rows[0]["avatar"].endswith("_400x400.png")
    assert rows[0]["raw"], "kolom raw (fallback avatar) harus tersedia"
    dbm.mark_notified(conn, iid)
    assert dbm.pending_notifications(conn, 10, require_translation=True) == []


def test_embed_dari_baris_db_punya_avatar(conn):
    """Regresi: baris dari pending_notifications harus bisa bikin embed ber-avatar."""
    from app.notify import build_embed

    items = _items()
    dbm.upsert_tweets(conn, items)
    iid = items[0]["id_str"]
    dbm.set_translated(conn, iid, "halo")
    row = dbm.pending_notifications(conn, 1, require_translation=True)[0]
    embed = build_embed(dict(row))
    assert embed["author"]["icon_url"], "embed tanpa icon_url (avatar member hilang!)"


def test_query_tweets_filter_dan_kursor(conn):
    items = _items()
    dbm.upsert_tweets(conn, items)
    all_rows, nb = dbm.query_tweets(conn, limit=1)
    assert len(all_rows) == 1 and nb is not None

    rows2, _ = dbm.query_tweets(conn, limit=10, before=nb)
    assert rows2
    assert all(r["created_at"] <= all_rows[0]["created_at"] for r in rows2)

    only_polka, _ = dbm.query_tweets(conn, member="polka_lion", limit=10)
    assert all(r["member"] == "polka_lion" for r in only_polka)

    # pencarian mencakup teks ID juga
    dbm.set_translated(conn, items[1]["id_str"], "kata-kata unik zzz")
    found, _ = dbm.query_tweets(conn, q="zzz", limit=10)
    assert [r["id_str"] for r in found] == [items[1]["id_str"]]


def test_translation_queue_only_pending(conn):
    """only_pending=True → fase notifikasi tidak menunggu backfill panjang."""
    items = _items()
    dbm.upsert_tweets(conn, items)
    ids = [i["id_str"] for i in items]
    dbm.mark_skipped(conn, ids[:2])  # 2 baris jadi backfill (bukan pending)

    semua = [r["id_str"] for r in dbm.translation_queue(conn, 10, 5)]
    assert set(semua) == set(ids)                              # keduanya ikut

    hanya_pending = [r["id_str"] for r in dbm.translation_queue(conn, 10, 5, only_pending=True)]
    assert hanya_pending == [ids[2]]                            # hanya yang menunggu notif


def test_meta_roundtrip(conn):
    dbm.set_meta(conn, "baseline_done", "true")
    assert dbm.get_meta(conn, "baseline_done") == "true"
    assert dbm.get_meta(conn, "tidak_ada", "fallback") == "fallback"
