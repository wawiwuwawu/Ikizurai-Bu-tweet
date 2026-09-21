"""Worker: loop utama (fetch → translate → notify) + CLI.

Alur (lihat plan):
  SETUP  : backfill penuh sekali → semua tweet lama notify_state='skipped' (baseline)
  SIKLUS : 1) fetch tweet baru (since = last_check − 1 hari, cache-buster)
           2) translate antrean (prioritas: yang menunggu notifikasi)
           3) kirim notifikasi Discord (hanya yang sudah diterjemahkan)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

from . import db as dbm
from .config import Settings, get_settings
from .notify import RateLimiter, build_payload, send_payload
from .source import make_session, paginate, parse_tweet
from .translate import TranslateError, clean_retry_backoff, translate_with_retry

log = logging.getLogger("ikizurai.worker")

NOTIFY_ORDER_MAX = 10  # maksimum kirim per siklus (rate limit aman)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Worker:
    def __init__(self, settings: Settings, conn, session: Optional[requests.Session] = None,
                 healthcheck_url: str = ""):
        self.s = settings
        self.conn = conn
        self.session = session or make_session()
        self.limiter = RateLimiter(sleep=time.sleep)

    # ------------------------------------------------------------ fetch
    def _upsert_pages(self, pages, *, mark: str) -> list[str]:
        all_new: list[str] = []
        for page in pages:
            items = [parse_tweet(t) for t in page if t.get("id_str")]
            items = [i for i in items if i["id_str"] and i["member"]]
            new_ids = dbm.upsert_tweets(self.conn, items)
            all_new.extend(new_ids)
        if all_new and mark:
            if mark == "skip":
                dbm.mark_skipped(self.conn, all_new)
            # mark == "pending" → biarkan default 'pending'
        return all_new

    def backfill(self) -> int:
        """Ambil seluruh arsip (pertama kali). Semua ditandai skipped (baseline)."""
        log.info("MULAI backfill penuh dari %s", self.s.source_base)
        pages = paginate(self.session, self.s.source_base, delay=0.5)
        new_ids = self._upsert_pages(pages, mark="skip")
        dbm.set_meta(self.conn, "baseline_done", "true")
        dbm.set_meta(self.conn, "last_check_utc", iso(utcnow()))
        total = dbm.stats(self.conn)["total"]
        log.info("Backfill selesai: +%d baru, total %d tweet (semua baseline=skipped)", len(new_ids), total)
        return len(new_ids)

    def fetch_new(self) -> list[str]:
        """Ambil tweet baru sejak pengecekan terakhir (−1 hari untuk jaga-jaga)."""
        last = dbm.get_meta(self.conn, "last_check_utc")
        since_dt = utcnow() - timedelta(days=8)
        if last:
            try:
                since_dt = datetime.fromisoformat(last.replace("Z", "+00:00")) - timedelta(days=1)
            except ValueError:
                pass
        since = since_dt.strftime("%Y-%m-%d")
        log.info("Cek tweet baru sejak %s", since)
        pages = paginate(self.session, self.s.source_base, since=since, cache_bust=True, delay=0.4)
        new_ids = self._upsert_pages(pages, mark="")

        # tweet "baru" yang usianya sudah tua (gap arsip) → jangan dinotifikasi
        fresh = []
        for i in new_ids:
            row = self.conn.execute("SELECT created_at FROM tweets WHERE id_str = ?", (i,)).fetchone()
            if not row:
                continue
            age_days = (utcnow() - datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))).days
            if age_days > 14:
                dbm.mark_skipped(self.conn, [i])
            else:
                fresh.append(i)
        dbm.set_meta(self.conn, "last_check_utc", iso(utcnow()))
        if new_ids:
            log.info("Tweet baru: %d (notifikasi: %d)", len(new_ids), len(fresh))
        return fresh

    # ------------------------------------------------------------ translate
    def translate_cycle(self, only_pending: bool = False, max_batches: Optional[int] = None) -> int:
        """Terjemahkan antrean. `only_pending` = hanya yang menunggu notifikasi."""
        if self.s.translate_paused:
            return 0
        done_total = 0
        limit = max_batches if max_batches is not None else self.s.translate_batch_per_cycle
        for _ in range(limit):
            rows = dbm.translation_queue(
                self.conn, self.s.translate_batch_size, self.s.translate_max_attempts,
                only_pending=only_pending,
            )
            if not rows:
                break
            tweets = [{"id_str": r["id_str"], "text": r["text"]} for r in rows]
            result: dict[str, str] = {}
            err: Optional[str] = None
            try:
                result, err = translate_with_retry(
                    self.session,
                    base_url=self.s.omniroute_base_url,
                    api_key=self.s.omniroute_api_key,
                    model=self.s.translate_model,
                    tweets=tweets,
                    reasoning_effort=self.s.translate_reasoning_effort or None,
                    max_tokens=self.s.translate_max_tokens,
                    attempts=2,
                    base_delay=5,
                    max_delay=30,
                )
                if not result and self.s.translate_model_fallback:
                    log.warning("model utama gagal (%s) → coba fallback %s", err, self.s.translate_model_fallback)
                    result, err = translate_with_retry(
                        self.session,
                        base_url=self.s.omniroute_base_url,
                        api_key=self.s.omniroute_api_key,
                        model=self.s.translate_model_fallback,
                        tweets=tweets,
                        reasoning_effort=None,
                        max_tokens=self.s.translate_max_tokens,
                        attempts=2,
                    )
            except TranslateError as e:
                log.error("translasi fatal: %s", e)
                err = str(e)

            if result:
                for rid, text in result.items():
                    dbm.set_translated(self.conn, rid, text)
                done_total += len(result)
                # tweet yang tidak terjemahkan di batch ini → jadwalkan retry
                missing = [t["id_str"] for t in tweets if t["id_str"] not in result]
                for mid in missing:
                    dbm.mark_translate_failure(self.conn, mid, clean_retry_backoff(1, self.s.translate_retry_backoff_min, self.s.translate_retry_backoff_max))
            else:
                log.warning("translasi batch gagal: %s", err)
                attempts_now = 0
                for t in tweets:
                    attempts_now = dbm.mark_translate_failure(
                        self.conn, t["id_str"],
                        clean_retry_backoff(1, self.s.translate_retry_backoff_min, self.s.translate_retry_backoff_max),
                    )
                if attempts_now >= self.s.translate_max_attempts:
                    log.error("tweet mencapai batas percobaan translasi (%d) — dilewati", attempts_now)
        return done_total

    # ------------------------------------------------------------ notify
    def notify_cycle(self) -> int:
        sent = 0
        rows = dbm.pending_notifications(
            self.conn, NOTIFY_ORDER_MAX,
            require_translation=not self.s.notify_without_translation,
        )
        for r in rows:
            payload = build_payload(dict(r))
            ok, info = send_payload(
                self.session, self.s.discord_webhook_url, payload,
                limiter=self.limiter, dry_run=self.s.dry_run,
            )
            if ok:
                dbm.mark_notified(self.conn, r["id_str"])
                sent += 1
                log.info("notif terkirim: %s (%s)", r["id_str"], info or "-")
            else:
                log.error("notif GAGAL untuk %s: %s", r["id_str"], info)
                if info.startswith("FATAL"):
                    # webhook invalid — hentikan agar tidak menabrak invalid-request budget
                    break
        return sent

    # ------------------------------------------------------------ orchestration
    def full_cycle(self) -> dict[str, Any]:
        stats_before = dbm.stats(self.conn)
        if stats_before["baseline_done"] != "true" and self.s.backfill_on_start:
            self.backfill()
        else:
            self.fetch_new()

        # 1) prioritaskan tweet yang menunggu notifikasi → kirim cepat
        translated_priority = self.translate_cycle(only_pending=True, max_batches=4)
        notified = self.notify_cycle()
        # 2) lanjutkan backfill translasi arsip (tidak memblokir notifikasi berikutnya)
        translated_backfill = self.translate_cycle(only_pending=False)

        return {
            "translated_priority": translated_priority,
            "translated_backfill": translated_backfill,
            "notified": notified,
            "stats": dbm.stats(self.conn),
        }

    def run_forever(self) -> None:
        log.info("Worker start (interval %d menit)", self.s.check_interval_minutes)
        while True:
            try:
                result = self.full_cycle()
                log.info("Siklus selesai: %s", json.dumps(result, ensure_ascii=False))
            except KeyboardInterrupt:
                log.info("Dihentikan oleh user")
                return
            except Exception as e:  # noqa: BLE001 — loop tidak boleh mati
                log.exception("Error siklus: %s", e)
            time.sleep(self.s.check_interval_minutes * 60)


# ---------------------------------------------------------------- CLI

def _cli() -> int:
    parser = argparse.ArgumentParser(description="Ikizurai-Bu tweet worker")
    parser.add_argument("--once", action="store_true", help="jalankan 1 siklus lalu keluar")
    parser.add_argument("--backfill", action="store_true", help="paksa backfill penuh (baseline)")
    parser.add_argument("--translate-n", type=int, default=0, help="terjemahkan N tweet dari antrean lalu keluar")
    parser.add_argument("--notify-dry", type=int, default=0, help="print payload notifikasi utk N tweet (tidak kirim)")
    parser.add_argument("--send", type=int, default=0, help="kirim N notifikasi pending (nyata)")
    parser.add_argument("--stats", action="store_true", help="print statistik DB")
    parser.add_argument("--reset-translations", action="store_true",
                        help="hapus semua terjemahan supaya diterjemahkan ulang (mis. setelah ganti prompt)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    errors = settings.validate(require_webhook=bool(args.send or args.notify_dry))
    if errors:
        for e in errors:
            log.error("konfigurasi: %s", e)
        if any("OMNIROUTE" in e for e in errors) or errors:
            return 1

    conn = dbm.connect(settings.db_path)
    dbm.init_db(conn)
    worker = Worker(settings, conn)

    if args.stats:
        print(json.dumps(dbm.stats(conn), ensure_ascii=False, indent=1))
        return 0
    if args.reset_translations:
        n = conn.execute(
            "UPDATE tweets SET text_id = NULL, translated_at = NULL, "
            "translate_attempts = 0, next_retry_at = NULL"
        ).rowcount
        conn.commit()
        print(f"{n} terjemahan direset — worker akan menerjemahkan ulang dengan prompt terbaru.")
        print("TIP: idealnya worker berhenti dulu (docker compose stop) saat reset, "
              "supaya hitungan siklus yang sedang jalan tidak tercampur.")
        return 0
    if args.backfill:
        worker.backfill()
        return 0
    if args.translate_n:
        # mode uji: langsung terjemahkan N tweet dari antrean, tampilkan hasil
        rows = dbm.translation_queue(conn, args.translate_n, settings.translate_max_attempts)
        if not rows:
            print("Antrean translasi kosong.")
            return 0
        tweets = [{"id_str": r["id_str"], "text": r["text"]} for r in rows]
        t0 = time.time()
        result, err = translate_with_retry(
            worker.session, base_url=settings.omniroute_base_url, api_key=settings.omniroute_api_key,
            model=settings.translate_model, tweets=tweets,
            reasoning_effort=settings.translate_reasoning_effort or None,
            max_tokens=settings.translate_max_tokens, attempts=3, base_delay=5, max_delay=45,
        )
        dt = time.time() - t0
        if not result:
            print(f"GAGAL: {err}")
            return 1
        for r in rows:
            tr = result.get(r["id_str"])
            if tr:
                dbm.set_translated(conn, r["id_str"], tr)
            print("-" * 60)
            print("JP:", r["text"][:140].replace("\n", " / "))
            print("ID:", (tr or "<TIDAK ADA>")[:200].replace("\n", " / "))
        print(f"\n{len(result)}/{len(tweets)} berhasil dalam {dt:.1f}s")
        return 0
    if args.notify_dry:
        rows = dbm.pending_notifications(conn, args.notify_dry, require_translation=not settings.notify_without_translation)
        for r in rows:
            print(json.dumps(build_payload(dict(r)), ensure_ascii=False, indent=1))
        print(f"\n{len(rows)} payload (dry-run, tidak dikirim)")
        return 0
    if args.send:
        rows = dbm.pending_notifications(conn, args.send, require_translation=not settings.notify_without_translation)
        sent = 0
        for r in rows:
            ok, info = send_payload(worker.session, settings.discord_webhook_url, build_payload(dict(r)),
                                    limiter=worker.limiter, dry_run=settings.dry_run)
            if ok:
                dbm.mark_notified(conn, r["id_str"])
                sent += 1
                print(f"OK  {r['id_str']} -> {info or 'sent'}")
            else:
                print(f"ERR {r['id_str']}: {info}")
                if info.startswith("FATAL"):
                    break
        print(f"\n{sent}/{len(rows)} terkirim")
        return 0

    # default: run
    if settings.run_once:
        result = worker.full_cycle()
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        worker.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
