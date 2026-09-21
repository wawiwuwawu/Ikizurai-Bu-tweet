# 🐦 Ikizurai-Bu Tweet

Bot + website arsip untuk tweet 10 member **イキヅライブ！LOVELIVE!BLUEBIRD** (IkizuLive) — lengkap dengan **terjemahan bahasa Indonesia otomatis** dan **notifikasi Discord**.

> Proyek penggemar non-resmi. Semua konten tweet adalah milik ©プロジェクトイキヅライブ！/ 株式会社KADOKAWA.

![Tampilan web viewer](docs/screenshot.png)

---

## ✨ Fitur

- **📡 Scraper otomatis** — memantau arsip X publik dan menyimpan tweet baru ke database SQLite (idempoten, anti-duplikat).
- **🇯🇵→🇮🇩 Translasi otomatis** — via gateway OpenAI-compatible (OmniRoute), batch 5 tweet/request, hasil rapi & natural (emoji, kaomoji, baris kosong, hashtag dipertahankan).
- **🔔 Notifikasi Discord webhook** *(fitur utama)* — satu pesan per tweet:
  ```
  高橋ポルカ · @polka_lion
  Tweet baru dari 高橋ポルカ (Takahashi Polka)
  どうしよう
  高校落ちた
  ━━━━━━━━━━━━━━
  🇮🇩 Terjemahan:
  Gimana ya…

  Aku nggak keterima SMA…
  🐦 IkizuLive X Archive • 14/03/2025 7:56 PM
  ```
  Warna embed = warna resmi karakter, avatar member, link ke tweet asli di judul + author.
- **🖥️ Web viewer** — React satu halaman: filter member, pencarian (JP & ID), rentang tanggal, toggle ID/JP/JP+ID, infinite scroll.
- **🐳 Docker** — satu container (backend + worker + frontend build).

## 🏗 Arsitektur

```
┌──────────────────────── ikizurai-bu-tweet (Docker) ─────────────────────────┐
│  FastAPI :8097                                                              │
│   ├── worker thread   cek sumber → simpan → translate → notify Discord      │
│   ├── /api/*          data untuk frontend                                   │
│   └── /               frontend React (hasil build)                          │
│                            │                                                │
│  volume ./data/archive.db  │                                                │
└────────────────────────────┼────────────────────────────────────────────────┘
                             ▼
              Discord webhook  →  channel penggemar
```

## 🚀 Quick Start (Docker)

```bash
git clone https://github.com/wawiwuwawu/Ikizurai-Bu-tweet.git
cd Ikizurai-Bu-tweet
cp backend/.env.example backend/.env
# isi DISCORD_WEBHOOK_URL & OMNIROUTE_API_KEY
docker compose up -d --build
```

Buka `http://localhost:8097` — bot otomatis **backfill seluruh arsip** saat pertama kali jalan (semua tweet lama tidak dikirim ke Discord, hanya tweet baru).

## ⚙️ Konfigurasi (`backend/.env`)

| Variabel | Default | Keterangan |
|---|---|---|
| `SOURCE_BASE` | `https://gsm-app.com/lovelive/ikizulive-x-archive` | Sumber data arsip |
| `DISCORD_WEBHOOK_URL` | — | **Wajib.** Webhook notifikasi |
| `CHECK_INTERVAL_MINUTES` | `10` | Interval pengecekan tweet baru |
| `OMNIROUTE_BASE_URL` / `OMNIROUTE_API_KEY` | — | Gateway translasi (OpenAI-compatible) |
| `TRANSLATE_MODEL` | `atria/Atria-Dawn-Preview` | Model terjemahan |
| `TRANSLATE_MODEL_FALLBACK` | *(kosong)* | Model cadangan bila model utama macet |
| `TRANSLATE_REASONING_EFFORT` | `none` | **Penting** untuk model reasoning — lihat `docs/research/atria_test_report.md` |
| `TRANSLATE_BATCH_SIZE` | `5` | Jumlah tweet per request translasi |
| `TRANSLATE_BATCH_PER_CYCLE` | `20` | Batas batch per siklus (backfill) |
| `TRANSLATE_PAUSED` | `false` | Set `true` untuk berhenti menerjemahkan sementara |
| `NOTIFY_WITHOUT_TRANSLATION` | `false` | Kirim ke Discord walau belum diterjemahkan |
| `DRY_RUN` | `false` | `true` = cetak payload, tidak benar-benar mengirim |
| `WORKER_ENABLED` | `true` | Matikan worker (web saja) |
| `PORT` | `8097` | Port web |

## 🧰 CLI

```bash
cd backend && source .venv/bin/activate   # atau pakai Docker exec

python -m app.worker --stats              # statistik database
python -m app.worker --backfill           # paksa backfill arsip penuh
python -m app.worker --translate-n 10     # terjemahkan 10 tweet dari antrean (uji kualitas)
python -m app.worker --notify-dry 3       # lihat payload embed (tidak dikirim)
python -m app.worker --send 3             # kirim 3 notifikasi pending (nyata)
python -m app.worker --once               # jalankan satu siklus penuh
```

## 💻 Development

```bash
# backend
cd backend
uv venv .venv && uv pip install -p .venv/bin/python -r requirements.txt
.venv/bin/python -m pytest                # 42 tes
.venv/bin/python -m uvicorn app.main:app --port 8097

# frontend (dev server dengan proxy ke :8097)
cd frontend
npm install && npm run dev                # http://localhost:5173
```

## 📚 Dokumentasi

- [`docs/PLAN.md`](docs/PLAN.md) — rencana implementasi lengkap + hasil riset sumber data.
- [`docs/research/atria_test_report.md`](docs/research/atria_test_report.md) — pengujian model translasi (kenapa `reasoning_effort=none`).
- [`docs/research/discord_webhook_research.md`](docs/research/discord_webhook_research.md) — referensi limit & praktik terbaik Discord webhook.

## 🤝 Kontribusi

PR & issue terbuka — lihat [`CONTRIBUTING.md`](CONTRIBUTING.md).

## ⚖️ Lisensi

Kode: [MIT](LICENSE). Konten tweet & karakter: milik pemegang hak masing-masing (proyek イキヅライブ！). Proyek ini non-komersial dan tidak berafiliasi dengan proyek resmi.
