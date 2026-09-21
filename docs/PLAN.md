# IkizuLive X Archive → Bot Discord + Web Viewer (Implementation Plan)

> **For Hermes:** Plan ini dibuat setelah riset langsung (2026-09-21). Bagian §2.4 & §2.5 diisi dari hasil sub-agen (tes model translasi & riset Discord webhook).

**Goal:** Bot Python ringan yang memantau arsip tweet Love Live! Bluebird (イキヅライブ！) dari `gsm-app.com`, menyimpan semua tweet ke database lokal, menerjemahkan Jepang→Indonesia via OmniRoute (`atria/Atria-Dawn-Preview`), mengirim notifikasi tweet baru ke Discord webhook, plus FE sederhana untuk menjelajah arsip (filter member/tanggal/pencarian, JP+ID).

**Architecture:** Satu container Python (FastAPI + worker background). Worker loop: cek API sumber → simpan ke SQLite → antrean translasi (batch) → kirim notifikasi Discord yang sudah diterjemahkan. FastAPI menyajikan JSON API + 1 halaman FE (tanpa build step). Deploy di server rumah (.151) dengan Docker; ekspos publik opsional via Nginx Proxy Manager + Cloudflare Tunnel di .116.

**Tech Stack:** Python 3.12 · FastAPI + Uvicorn · SQLite (stdlib `sqlite3`) · requests · OmniRoute OpenAI-compatible API · Discord Webhook REST (langsung, tanpa library berat) · HTML+JS (vanilla, Tailwind CDN)

---

## 1. Jawaban Singkat atas Pertanyaan

| Pertanyaan | Rekomendasi |
|---|---|
| Scrape dulu atau translate dulu? | **Scrape dulu, translasi menyusul otomatis.** Semua tweet disimpan dalam bahasa Jepang asli + kolom terjemahan terpisah. Pipeline translasi jalan sebagai tahap sendiri yang bisa di-backfill belakangan (2463 tweet lama) tanpa memblokir scraper/notifikasi. |
| Notifikasi pakai apa? | **Discord webhook** (bukan ntfy), embed kaya: nama+avatar member, teks JP asli, terjemahan Indonesia, link ke post X, warna per member. |
| FE seperti apa? | **1 halaman HTML** disajikan FastAPI: filter member, pencarian, rentang tanggal, toggle JP/ID, infinite scroll. Tanpa build step, tanpa framework. |
| Model translasi? | `atria/Atria-Dawn-Preview` via OmniRoute yang sudah ada (128k context, gratis). Detail setup di §2.4. |

---

## 2. Hasil Riset (Fakta Terverifikasi)

### 2.1 Sumber Data — `gsm-app.com/lovelive/ikizulive-x-archive/`

Situs SPA (React+Vite, Hono RPC) di belakang Cloudflare. **Data diambil dari API JSON milik situs** (bukan scraping HTML):

```
GET https://gsm-app.com/lovelive/ikizulive-x-archive/api/x/posts
```

**Parameter (terverifikasi dengan tes langsung):**

| Param | Format | Catatan |
|---|---|---|
| `since` | `YYYY-MM-DD` | inklusif; format lain → ZodError |
| `until` | `YYYY-MM-DD` | inklusif |
| `q` | teks bebas | full-text search (Jepang OK) |
| `from` | `screen_name` | filter member, mis. `polka_lion` |
| `pagination_token` | `id_str` tweet terakhir | halaman berikutnya; 30 item/halaman, urut lama→baru |

- Tanpa param → 30 tweet **terlama** dulu (2025-03-14). Untuk data baru: pakai `since=<tanggal terakhir>` lalu paginate.
- Endpoint di-cache Cloudflare (`cache-control: max-age=14400`); tambahkan `?_=<epoch>` untuk bypass cache saat butuh data segar (terbukti `x-cs: MISS` → origin).
- `robots.txt` = 404 (tidak ada larangan eksplisit). Sopan-santun: 1-2 request per siklus cek, jeda 0.4-0.6s saat backfill.
- Tidak ada endpoint API lain (hanya `x.posts.$get`).

**Isi arsip (hasil download penuh 2026-09-21):**

- **2.463 tweet**, 2025-03-14 → 2026-09-18, 10 member.
- Distribusi member: ShaunTheBunny 327, polka_lion 289, My_Mai_Eld 267, hanabistarmine 250, G_Akky304250 246, Noricco_U 244, LittlegreenCom 229, MiracleGoldSP 207, Yukuri_talk 203, Rollie_twinkle 201.
- Aktivitas: ~5-22 tweet/hari (hari kerja saja — Sabtu/Minggu kosong), puncak 13:00-21:00 WIB.
- Ada **gap hiatus 2026-02-27 → 2026-09-05** (190 hari) — data hilang di sumber, bukan error kita.
- Struktur tweet = format X API v1.1: `id_str, text, created_at, user{screen_name,name,profile_image_url_https}, favorite_count, conversation_count, entities{hashtags,urls,user_mentions,media}, quoted_tweet(32x), mediaDetails(2x), card(11x)`.
- Media/gambar sangat jarang (2 dari 2463). Mayoritas teks murni; hashtag `#いきづらい部` di 2177 tweet.
- Panjang teks: median 78 char, max 154.
- Teks dipisah baris kosong antar paragraf (`\n\n`) — prompt & render FE harus mempertahankan ini.

**Daftar member (untuk filter FE + warna Discord):**

| # | Nama JP | Screen name | Emoji khas |
|---|---|---|---|
| 1 | 高橋ポルカ | polka_lion | 🦁🌻 |
| 2 | 麻布麻衣 | My_Mai_Eld | 💢 |
| 3 | 五桐玲 | G_Akky304250 | 🐱🎤 |
| 4 | 駒形花火 | hanabistarmine | 🎆 |
| 5 | 金澤奇跡 | MiracleGoldSP | ✨ |
| 6 | 調布のりこ | Noricco_U | 📮❄️ |
| 7 | 春宮ゆくり | Yukuri_talk | 🩰 |
| 8 | 此花輝夜 | Rollie_twinkle | 🌈✨ |
| 9 | 山田真緑 | LittlegreenCom | 🌎 |
| 10 | 佐々木翔音 | ShaunTheBunny | 🐰 |

### 2.2 Infrastruktur Deploy (terverifikasi)

- **.116 (CasaOS VM104)** = pintu masuk publik home network: `cloudflared` (tunnel) + `nginxproxymanager` (NPM, port 80/443) + FlareSolverr + **bot lama `bot-notify` (notifikasi-scrape-web) jalan di sini** (`~/notifikasi-scrape-web`, compose project).
- **.151 (hermes-ww)**: Docker host utama (omniroute, yt-downloader, dst). Docker root `/mnt/data/docker`.
- Subdomain publik `*.wawunime.my.id` semua resolve ke .116 → NPM → upstream LAN. Contoh: `omniroute.wawunime.my.id`.
- Pola deploy user: `docker-compose.yml` + `.env` + volume `./data:/app/data` + `restart: unless-stopped` + `CHECK_INTERVAL_MINUTES` loop + `RUN_ONCE` flag (dari repo `notifikasi-scrape-web` & varian `Notifikasi-scrape-web-via-discord`).

**Keputusan:** app jalan di **.151** (port **8097**), FT via NPM .116 (proxy host → `192.168.0.151:8097`) + public hostname cloudflared (mis. `ikizulive.wawunime.my.id`) — opsional, bisa ditunda.

### 2.3 Pola Proyek Referensi (yang akan dipertahankan)

Dari `notifikasi-scrape-web` (+ varian Discord yang sudah ada di .116):
- Dedupe via history/link → diganti **dedupe via PRIMARY KEY id_str di SQLite** (lebih kuat).
- Webhook gagal → tetap dicoba ulang (jangan tandai terkirim sebelum sukses).
- Log ber-emoji, pesan Indonesia, validasi config saat startup (`validate_config()`).
- Dockerfile `python:3.12-slim`, `TZ=Asia/Jakarta`, compose dengan logging max-size 10m/3 file.
- Varian Discord lama pakai `discord_webhook` lib + `deep-translator`. → **Ganti** dengan REST langsung + OmniRoute (lebih ringan, tanpa dependensi translasi eksternal).

### 2.4 Translasi — `atria/Atria-Dawn-Preview` via OmniRoute

- Endpoint: `POST https://omniroute.wawunime.my.id/v1/chat/completions`, OpenAI-compatible.
- Model confirmed ada: `atria/Atria-Dawn-Preview`, `context_length: 128000`, capabilities: tool_calling + reasoning.
- Provider origin: `https://api.atria-asi.ai/v1` (openai-compatible, 1 connection "rdsmail", `proxy_enabled=1`) — ditambahkan ke OmniRoute 2026-09-21.
- **Karakteristik stabilitas (dari `call_logs` OmniRoute 30 hari + monitor):** flaky. Histori: 10× `200 OK`, 28× `504`, 7× `502`, 7× `503`.
  - Gejala: OmniRoute membalas `504 RATE_LIMIT_EXECUTION_TIMEOUT` (queue lokal maxWaitMs=15s) atau `model_cooldown` ("All credentials for model Atria-Dawn-Preview are cooling down") saat upstream (nginx `api.atria-asi.ai`) membalas 502/503/504.
  - Tapi **request yang lolos berhasil dengan baik** (sukses terakhir 14:14:35, latency 3-56 detik; ada yang 56s).
  - Artinya: **bisa dipakai, tapi WAJIB desain antrean yang tabah** — retry berjenjang (bukan 3× cepat), backoff sampai puluhan menit, progres tersimpan (SQLite), dan opsi fallback model.
- ⚠️ Error `RATE_LIMIT_EXECUTION_TIMEOUT` + latency tinggi → **akar masalahnya sudah ditemukan & dipecahkan** (lihat di bawah).
- **Hasil tes final (✅ teruji dengan output nyata):**

| Parameter | Nilai final | Bukti |
|---|---|---|
| **`reasoning_effort`** | **`"none"`** ← kunci utama | Tanpa ini: reasoning token makan budget (600/600 → output kosong; 24-56s → 504). Dengan ini: 1-12s, 0 token reasoning, bebas 504 |
| Batch | **5 tweet/request** | Log final: 5 tweet = 12,2 detik, parse **5/5** |
| Format output | JSON `[{"id","id_text"}]` | Parse 5/5 (batch 5), 3/3 (batch 3), 2/2 (batch 2) |
| max_tokens | 2500 | Batch 5 hanya pakai ~541 token output |
| temperature | 0.3 | — |
| Estimasi backfill 2.463 tweet | **~493 request ≈ 1,7 jam** (realistis 2-3 jam dgn jeda+retry) | — |
| Retry | Wajib (upstream flaky 502/503/504) — tapi dgn effort=none semua percobaan final sukses | — |

- **System prompt final (P4):** "Kamu penerjemah profesional Jepang→Indonesia untuk konten anime (Love Live! Bluebird / イキヅライブ！) … SEMUA kata dalam bahasa Indonesia … emoji/kaomoji/newline dijaga … nama romaji … hashtag dibiarkan … Output HANYA JSON array" — teks lengkap di `atria_test_report.md` §2.3.
- Contoh kualitas: どうしよう → "Gimana ya…"; emoji & "。。。"/"ーー" utuh; istilah brand dipertahankan.
- 📄 Laporan lengkap: `~/ikizulive-x-research/atria_test_report.md`

**Rekomendasi desain (mengantisipasi flakiness):**
1. Retry berjenjang dalam worker: attempt cepat (3×, jeda 5-15s) → lalu mode tabah (retry tiap 2-10 menit, maksimum menunggu berjam-jam, `translate_attempts` disimpan).
2. `TRANSLATE_MODEL_FALLBACK` (opsional, default kosong): model lain di gateway yang dipakai bila atria gagal terus (mis. `auto/best-fast`).
3. Backfill dijalankan sebagai job background dengan checkpoint per batch → aman restart kapan saja.
4. Progres & reliabilitas dipantau via `/api/stats` + log.

### 2.5 Discord Webhook (riset selesai + tes live ✅)

**Status: webhook user sudah diverifikasi hidup.** `GET` → 200, name=`Love Live Bluebird`, `channel_id=1551597589982609498`. Tes kirim nyata: pesan tes = 200 (lalu dihapus), **embed preview = 204 (sukses, ada di channel)**. URL disimpan di `.env` sebagai `DISCORD_WEBHOOK_URL` (tidak ditulis di plan ini — anggap password).

**Fakta kunci (dokumentasi resmi Discord + verifikasi empiris):**

| Hal | Nilai | Status |
|---|---|---|
| Rate limit pesan | **30 pesan/menit per webhook** | ✅ resmi (Safety Center) — volume kita 5-20/hari, sangat lega |
| Bucket burst | ~5 req/2 detik | ⚠️ komunitas — **jangan hardcode**, baca header `X-RateLimit-*` |
| 429 | `retry_after` = float **detik** dari body; `global:true` → stop semua worker | ✅ |
| 401/403/404 | **Jangan retry** (budget invalid 10.000/10 menit → IP ban) | ✅ |
| Embed per pesan | 10 | ✅ |
| description / title / footer | 4096 / 256 / 2048 | ✅ |
| Total teks semua embed per pesan | 6000 char | ✅ (teks arsip max 154 → aman total) |
| Gambar eksternal `pbs.twimg.com` | Boleh langsung (Discord proxy+cache) | ✅ terverifikasi HTTP 200 |
| Avatar | Wajib ganti `_normal` → `_400x400` (48px pecah di Discord) | ✅ |
| `allowed_mentions: {"parse": []}` | **Wajib** — default webhook = ping users; teks tweet bisa memicu mention | ✅ |
| URL di `content` | Jangan — memicu link preview. Link "Buka di X ↗" via `embed.title` + `embed.url` | ✅ |
| `?wait=true` | Ya — kegagalan jadi terlihat + dapat `message_id` untuk log/delete | ✅ |
| Warna member | Deterministik: `SHA256(screen_name)` → HSV(h, 0.65, 0.95) → int | desain |
| Teks | Normalisasi `\n{3,}` → `\n\n` (1847 tweet punya baris kosong ganda) | desain |
| Backfill | **Tidak dikirim** — watermark `last_seen_id_str` di-set saat inisialisasi | desain |

**Desain embed final (1 pesan per tweet, 1 embed):**

```json
{
  "username": "高橋ポルカ@いきづらい部！",
  "avatar_url": "https://pbs.twimg.com/profile_images/.../uOWsSYJW_400x400.png",
  "allowed_mentions": { "parse": [] },
  "embeds": [{
    "author": {"name": "@polka_lion", "url": "<tweet url>", "icon_url": "<avatar 400x400>"},
    "title": "Buka di X ↗",
    "url": "https://x.com/polka_lion/status/1900531357174128835",
    "description": "どうしよう\n\n高校落ちた\n\nどうしようどうしようどうしよう\n\n— 🇮🇩 Terjemahan —\nGimana ini\n\nAku nggak keterima SMA\n\nGimana ini... gimana ini... gimana ini",
    "color": 12382804,
    "timestamp": "2025-03-14T12:56:00.000Z",
    "footer": {"text": "Love Live! Bluebird • ❤ 2090"}
  }]
}
```

Batching hanya bila burst ekstrem (queue > 3 dalam < 30 detik) → gabung maks 5-10 embed/pesan. Media tweet (2 kasus) → `embed.image.url` langsung dengan URL `:large`.

Laporan lengkap: `~/ikizulive-x-research/discord_webhook_research.md` (limit lengkap, pseudocode rate-limit handler, sumber resmi).

---

## 3. Arsitektur

```
┌─────────────────────────────── .151 (Docker) ────────────────────────────────┐
│  container: ikizulive-bot  (python:3.12-slim)                                │
│                                                                              │
│  ┌──────────── worker thread (loop tiap CHECK_INTERVAL) ─────────────────┐   │
│  │ 1. FETCH   GET api/x/posts?since=<terakhir>  (cache-buster ?_=ts)     │   │
│  │ 2. STORE   upsert SQLite (PK id_str) — tweet baru ditandai pending    │   │
│  │ 3. TRANSLATE  ambil N baris text_id IS NULL → batch ke OmniRoute      │   │
│  │    (retry + backoff; prioritas: tweet baru > backfill)                │   │
│  │ 4. NOTIFY  tweet yang sudah diterjemahkan & belum terkirim →          │   │
│  │    Discord webhook (embed: nama, avatar, JP, ID, link X)              │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  uvicorn (FastAPI) :8097                                                     │
│    GET /                → FE (index.html, vanilla JS)                        │
│    GET /api/tweets      → ?from=&q=&since=&until=&before=&limit=30           │
│    GET /api/members     → daftar 10 member + count                           │
│    GET /api/stats       → total tweet, terjemahan, terakhir dicek            │
│                                                                              │
│  volume: ./data/archive.db (SQLite, WAL)                                     │
└──────────────────────────────────────────────────────────────────────────────┘
        │  (opsional)                                    ▲
        ▼                                                │
  NPM .116 → cloudflared → https://ikizulive.wawunime.my.id ──┘
        │
        ▼
  Discord webhook  ──►  channel Discord user
```

**Prinsip:**
- **Idempoten** — jalankan ulang kapan saja; PK `id_str` mencegah duplikat.
- **Gagal aman** — notifikasi hanya ditandai terkirim setelah Discord balas 2xx; translasi gagal → retry dengan limit (`translate_attempts`).
- **Backfill ≠ spam** — run pertama mengimpor 2463 tweet sebagai baseline (tidak dinotifikasi). Notifikasi hanya untuk tweet yang muncul setelah inisialisasi.
- **Fase terpisah** — scraper tidak menunggu translasi; FE bisa menampilkan JP walau ID belum jadi.

---

## 4. Skema Database (SQLite)

```sql
CREATE TABLE IF NOT EXISTS tweets (
  id_str            TEXT PRIMARY KEY,
  member            TEXT NOT NULL,        -- screen_name
  member_name       TEXT,                 -- display name JP (高橋ポルカ)
  created_at        TEXT NOT NULL,        -- ISO UTC dari sumber
  text              TEXT NOT NULL,        -- teks Jepang asli (verbatim)
  text_id           TEXT,                 -- terjemahan Indonesia (NULL = belum)
  translated_at     TEXT,
  translate_attempts INTEGER DEFAULT 0,
  favorite_count    INTEGER,
  conversation_count INTEGER,
  is_reply          INTEGER DEFAULT 0,
  quoted_tweet      TEXT,                 -- JSON blob (opsional)
  media             TEXT,                 -- JSON array media (jarang)
  url               TEXT NOT NULL,        -- https://x.com/<user>/status/<id>
  raw               TEXT,                 -- JSON asli utuh (untuk re-parse)
  fetched_at        TEXT NOT NULL,
  notify_state      TEXT DEFAULT 'pending', -- pending | skipped | sent
  notified_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_tweets_created  ON tweets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_member   ON tweets(member, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tweets_translate ON tweets(text_id, translate_attempts);
CREATE INDEX IF NOT EXISTS idx_tweets_notify   ON tweets(notify_state);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);  -- last_check_utc, baseline_done, translate_paused, dsb.
```

---

## 5. Alur Kerja (Worker Loop)

```
SETUP (sekali):
  if meta.baseline_done != true:
      backfill()            # paginate sejak 2025-03-14 sampai habis (83 req, jeda 0.5s)
      semua tweet → notify_state='skipped' (baseline, tidak dinotifikasi)
      meta.baseline_done = true

SETIAP SIKLUS (tiap CHECK_INTERVAL_MINUTES, default 10):
  1. FETCH:  GET posts?since=<last_check − 1 hari>&_=<epoch>
             paginate sampai halaman < 30 → upsert; yang benar-benar baru:
             notify_state='pending'
  2. TRANSLATE: ambil ≤ TRANSLATE_BATCH_PER_CYCLE batch (default: 20 batch × 5 tweet)
             prioritas: (a) notify_state='pending' (butuh untuk notifikasi),
                        (b) backfill: created_at DESC (terbaru dulu)
             → POST OmniRoute: {model, reasoning_effort:"none", max_tokens:2500, batch 5 tweet JSON}
             → sukses (parse JSON) → simpan text_id; gagal → attempts++ + backoff (max attempts)
  3. NOTIFY:  ambil tweet notify_state='pending' AND text_id NOT NULL
             → kirim embed Discord SATU PESAN PER TWEET (single worker!):
               username+avatar member, allowed_mentions={parse:[]}, ?wait=true
               pacing dari header X-RateLimit-* (jangan hardcode), 429→sleep retry_after
             → sukses (200/204): notify_state='sent' + simpan message_id
             → gagal permanen (401/403/404): log + alert, JANGAN retry
  4. meta.last_check_utc = now
```

Catatan urutan: notifikasi menunggu terjemahan (biar pesan Discord langsung enak dibaca). Jika translasi sedang `paused` (mis. model down), notifikasi tetap tertahan (tidak kirim setengah matang) — atau mode `NOTIFY_WITHOUT_TRANSLATION=true` untuk fallback.

---

## 6. FE Sederhana

**File:** `web/static/index.html` (1 file; fetch ke API sendiri). Data avatar langsung dari `pbs.twimg.com` (sudah ada di data).

**Fitur:**
1. Header: judul ID + total tweet + status terakhir dicek.
2. Baris filter: chip 10 member (klik toggle), search box (cari di teks JP & ID — SQLite `LIKE`), date range (2 input date), toggle tampilan: `JP` / `ID` / `JP+ID`.
3. Daftar tweet (infinite scroll, 30/halaman): avatar, nama member, @handle, waktu (WIB), teks (sesuai toggle; `\n\n` dirender jadi paragraf), ❤ jumlah, link "Buka di X ↗".
4. Badge kecil "ID" jika terjemahan tersedia; kalau belum, tampil JP saja + label "belum diterjemahkan".

**API (FastAPI):**
| Endpoint | Query | Respons |
|---|---|---|
| `GET /api/tweets` | `from, q, since, until, before (id_str), limit=30` | `{items: [...], next_before: "..." \| null}` |
| `GET /api/members` | — | `[{screen_name, name, count}]` |
| `GET /api/stats` | — | `{total, translated, last_check}` |

---

## 7. Deployment

- **Port:** 8097 di .151 (cek bebas sebelum dipakai).
- **Folder deploy di server:** `/home/dede/ikizulive-x-archive` (ikuti pola `~/notifikasi-scrape-web`).
- **Compose:**

```yaml
services:
  ikizulive:
    build: .
    container_name: ikizulive-archive
    restart: unless-stopped
    env_file: [.env]
    ports: ["8097:8097"]
    volumes: ["./data:/app/data"]
    logging:
      driver: json-file
      options: {max-size: "10m", max-file: "3"}
```

- **Ekspos publik (opsional, belakangan):** NPM .116 → Add Proxy Host → domain `ikizulive.wawunime.my.id` → forward `192.168.0.151:8097` → SSL Let's Encrypt → lalu tambah Public Hostname di cloudflared (`http://192.168.0.116:<NPM port>`).

---

## 8. Rencana Eksekusi (Tasks)

> Konvensi: TDD (tes dulu), commit per task, konfirmasi user sebelum push.

### 🔴 Fase 1 — Fondasi (repo & data source)
- [ ] **T1.1** `git init` folder `~/ikizulive-x-archive`; struktur folder (`bot/`, `web/`, `tests/`, `data/`, `research/`); `.gitignore` (`data/`, `.env`, `__pycache__`).
- [ ] **T1.2** `requirements.txt`: `fastapi`, `uvicorn[standard]`, `requests`, `python-dotenv`, `pytest`, `pytest-mock`; venv via `uv venv`.
- [ ] **T1.3** `bot/config.py` — baca `.env` + `validate_config()` (pola repo lama).
- [ ] **T1.4** `bot/db.py` — buat skema SQL (di atas) + fungsi `upsert_tweets()`, `get_pending_translations()`, `get_pending_notifications()`, `set_translated()`, `set_notified()`, `get_meta()/set_meta()`.
  - Tes: `tests/test_db.py` — upsert idempoten (2x insert id sama → 1 baris), queue query benar.
- [ ] **T1.5** `bot/source.py` — `fetch_page(params)`, `paginate(since=None)`, `parse_tweet(raw) → dict` (ekstrak media/quote/url).
  - Tes: `tests/test_source.py` dengan fixture JSON nyata (ambil 3 tweet dari `research/raw_archive.json`); tes pagination pakai mock; tes `since` + `?_=` cache-buster.
  - Verifikasi nyata: jalankan `python -m bot.source --since 2026-09-17` → print jumlah tweet didapat.

### 🟠 Fase 2 — Translasi (OmniRoute)
- [ ] **T2.1** `bot/translate.py` — klien OpenAI-compatible: `translate_batch(tweets) → {id: text_id}`.
  - Config final (§2.4): `reasoning_effort="none"`, `max_tokens=2500`, `temp=0.3`, batch 5, output JSON `[{"id","id_text"}]`, prompt P4 (copy dari `atria_test_report.md` §2.3).
  - Parser JSON toleran (strip markdown fence, ambil `[...]` pertama-terakhir) + validasi semua id terisi.
  - Retry: error transient (timeout/502/503/504/cooldown) → backoff eksponensial (dari `TRANSLATE_RETRY_BACKOFF_MIN` ke `MAX`); error fatal (401/400) → tandai + skip model.
  - Timeout request 120s (upstream kadang lambat walau effort=none).
  - Tes unit dengan mock HTTP (sukses, timeout, JSON rusak, JSON dengan fence).
- [ ] **T2.2** Script uji nyata: `python -m bot.translate --test 10` → ambil 10 tweet dari DB, terjemahkan (2 batch × 5), tampilkan hasil + latency.
  - **Verifikasi manual user:** cek 10 hasil terjemahan (kualitas + gaya).

### 🟡 Fase 3 — Discord Notifier
- [ ] **T3.1** `bot/notify.py` — sesuai §2.5: payload embed (author+avatar `_400x400`, title "Buka di X ↗"+url, description JP+ID, warna member SHA256→HSV, timestamp tweet, footer ❤ count), `allowed_mentions={"parse":[]}`, `?wait=true`, pacing header-driven (`X-RateLimit-Remaining/Reset-After`), 429→`retry_after`, 401/403/404 tidak di-retry, normalisasi `\n{3,}`, single worker.
  - Tes unit: mock 204 (→tandai sent), mock 429 (→tidak ditandai, sleep), mock 404 (→failure permanen, tidak retry).
- [ ] **T3.2** `DRY_RUN=true` mode → print payload JSON tanpa kirim; bandingkan dengan preview embed yang sudah ada di channel.
- [ ] **T3.3** Tes kirim nyata 3-5 tweet ke webhook user → cek tampilan di Discord + header `X-RateLimit-*` (konfirmasi angka bucket sesungguhnya).
- [ ] **T3.4** Watermark backfill: saat inisialisasi catat `last_seen_id_str` tertinggi → semua ≤ watermark `notify_state='skipped'`.

### 🟢 Fase 4 — Web API + FE
- [ ] **T4.1** `web/api.py` — 3 endpoint (§6) + serve static.
- [ ] **T4.2** `web/static/index.html` — FE (vanilla JS + Tailwind CDN); render paragraf `\n\n`, toggle JP/ID, infinite scroll.
- [ ] **T4.3** Verifikasi visual: buka `http://192.168.0.151:8097` → screenshot; tes filter/search/pagination.

### 🔵 Fase 5 — Integrasi Worker + Backfill
- [ ] **T5.1** `bot/worker.py` + `bot/main.py` — loop §5 (baseline logic, prioritas antrean, `RUN_ONCE`).
- [ ] **T5.2** Jalankan backfill import penuh (83 request, ~1 menit) → verifikasi count 2463 & semua `skipped`.
- [ ] **T5.3** Jalankan backfill translasi penuh di background (estimasi dari §2.4) → monitor progres via log + `/api/stats`.
- [ ] **T5.4** Simulasi tweet baru: set `since` ke hari berjalan / tunggu tweet asli muncul → pastikan muncul di Discord + FE.

### 🟣 Fase 6 — Deploy & Dokumentasi
- [ ] **T6.1** Dockerfile + docker-compose → `docker compose up -d --build` di .151; cek health + log.
- [ ] **T6.2** (Opsional) NPM + cloudflared → subdomain publik; verifikasi dari luar.
- [ ] **T6.3** README (cara setup, env, cara ganti webhook, cara pause translasi) + `docs/` ringkasan riset.
- [ ] **T6.4** Commit terakhir + (setelah konfirmasi) push ke GitHub `wawiwuwawu/ikizulive-x-archive` (private).

---

## 9. Konfigurasi `.env`

```env
# === Sumber ===
SOURCE_BASE=https://gsm-app.com/lovelive/ikizulive-x-archive
CHECK_INTERVAL_MINUTES=10

# === Discord ===
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
NOTIFY_WITHOUT_TRANSLATION=false

# === OmniRoute (translasi) ===
OMNIROUTE_BASE_URL=https://omniroute.wawunime.my.id/v1
OMNIROUTE_API_KEY=sk-xxxx
TRANSLATE_MODEL=atria/Atria-Dawn-Preview
TRANSLATE_MODEL_FALLBACK=            # opsional, mis. auto/best-fast (dipakai bila atria gagal terus)
TRANSLATE_REASONING_EFFORT=none      # WAJIB "none" utk atria (reasoning model) — lihat §2.4
TRANSLATE_MAX_TOKENS=2500
TRANSLATE_BATCH_SIZE=5               # teruji: 5 tweet = 12,2s, parse 5/5
TRANSLATE_BATCH_PER_CYCLE=20         # ~20 batch/siklus (10 menit) utk backfill cepat
TRANSLATE_MAX_ATTEMPTS=5
TRANSLATE_RETRY_BACKOFF_MIN=60       # detik; retry berjenjang utk error upstream (502/503/504/cooldown)
TRANSLATE_RETRY_BACKOFF_MAX=900
TRANSLATE_PAUSED=false

# === Web ===
PORT=8097
TZ=Asia/Jakarta
RUN_ONCE=false
DRY_RUN=false
```

---

## 10. Risiko & Catatan

1. **Server sumber pihak ketiga (unofficial)** — api/x/posts bisa berubah/rate-limit kapan saja. Mitigasi: klien terisolasi di `source.py`, error tidak mematikan loop, cache-buster dipakai hemat.
2. ✅ **Latency/504 model — SUDAH DIPECAHKAN.** Akar masalah: reasoning token model atria. Solusi teruji: `reasoning_effort="none"` → 1-12 detik/request (dari 24-56s) & bebas 504. Sisa risiko tinggal flakiness upstream (502/503/504) → ditangani retry berjenjang + antrean persisten.
3. **Kuota/limit gateway gratis** — bisa berubah sewaktu-waktu. Mitigasi: `TRANSLATE_PAUSED`, fallback model opsional, progres tersimpan (aman restart kapan saja).
4. **Gap data di sumber** (2026-02-27 → 09-05) — bukan bug; FE sebaiknya tidak menampilkan "hari kosong" sebagai masalah.
5. **Tweet baru vs cache Cloudflare 4 jam** — selalu pakai `?_=<epoch>` saat cek tweet baru, jangan saat backfill (biar cache membantu).
6. **Konten karakter** — tweet = roleplay akun resmi proyek; terjemahan harus menjaga tone (glossary nama & hashtag) — prompt P4 + aturan "semua kata bahasa Indonesia" sudah teruji menangani ini.
7. **Jangan spam channel** — baseline di-skip; burst (mis. 20 tweet sehari) tetap wajar untuk Discord.
8. **Ukuran batch ≠ kaku** — 5 tweet/request adalah titik aman teruji; bisa dinaikkan setelah backfill terbukti stabil.

---

## 11. Pertanyaan Terbuka (butuh keputusan user)

1. **Nama repo & lokasi:** `ikizulive-x-archive` di `~/` (.151)? Push ke GitHub kapan (default: jangan push dulu)?
2. **Ekspos publik FE:** perlu subdomain `ikizulive.wawunime.my.id` atau cukup LAN dulu?
3. **Warna embed per member:** default desain = hash deterministik dari screen_name (konsisten, cepat). Mau ganti palet warna resmi per karakter? (perlu riset kecil, bisa nyusul)
4. **Terjemahan di Discord:** cek **preview embed yang sudah dikirim ke channel kamu** — mau format itu (JP+ID dalam satu embed), atau ID saja?
5. **Backfill translasi:** langsung semua 2463 (~2-3 jam background), atau bertahap (mis. 500 terbaru dulu)?
6. **Mockup FE:** cek mockup di atas — layout/fitur sudah cocok? (filter member, search, rentang tanggal, toggle JP/ID, infinite scroll)

---

## 12. Lampiran Riset (artefak)

- `~/ikizulive-x-research/raw_archive.json` — 2463 tweet mentah (backup lokal penuh).
- `~/ikizulive-x-research/sample_tweets.json` — 18 sampel tweet untuk uji translasi.
- `~/ikizulive-x-research/atria_test_report.md` — hasil tes translasi.
- `~/ikizulive-x-research/atria_test_results/` — script + log tes translasi (termasuk `patient_test.log`).
- `~/ikizulive-x-research/discord_webhook_research.md` — referensi Discord webhook (limit resmi + pseudocode rate-limit).
- `~/ikizulive-x-research/discord_docs/` — salinan dokumentasi Discord (rujukan ulang).
- `~/ikizulive-x-research/test_api_edges.py` — bukti tes parameter API sumber.
- `~/ikizulive-x-research/discord_test.py` — tes live webhook (GET info + kirim + hapus).
