# Plan v2 — Publikasi Data & Viewer GitHub Pages

> Status: **usulan, belum dieksekusi.** Semua angka di bawah hasil pengukuran langsung (2026-09-21).

## 0. Jawaban singkat

| Pertanyaan | Jawaban |
|---|---|
| Bisa upload semua hasil translate + database ke GitHub? | **Ya** — tapi formatnya **JSONL** (1,28 MB), bukan file SQLite (5,9 MB binary yang tiap update bikin riwayat repo membengkak). DB siap-pakai → taruh di **GitHub Releases**, bukan di git. |
| Bisa di-host di GitHub Pages? | **Sebagian.** Worker + API + database TIDAK bisa (Pages = static only). Tapi **viewer-nya BISA** jadi situs static penuh — dan justru itu yang dibutuhkan "orang bisa lihat sendiri tanpa server". |
| Bonus yang mungkin belum kepikiran | **GitHub Actions bisa jadi "server" gratis** (cron + secrets) → proyek tetap hidup walau server rumah mati, dan orang lain bisa fork & jalankan sendiri. Gratis unlimited menit untuk repo public (sesuai prinsipmu: no tagihan). |

---

## 1. Publikasi data — pilihan format

| Opsi | Ukuran | Untuk git | Catatan |
|---|---|---|---|
| **JSONL per bulan** `data/tweets/2025-03.jsonl` | ~101 KB/bulan (**total 1,28 MB**) | ✅ **ideal** | Diff-able (cuma baris berubah yang tercatat), bisa di-seed ulang, pertumbuhan wajar (+~100 KB/bulan) |
| JSONL gabungan 1 file | 1,28 MB | ✅ | Sederhana, tapi tiap update menulis ulang file besar |
| `archive.db` (SQLite) di git | 5,9 MB binary | ❌ | Setiap update = blob baru; 100 commit ≈ 600 MB riwayat |
| `archive.db` di **GitHub Releases** | 5,9 MB/rilis | ✅ | Asset download, tidak mengotori riwayat git |
| Git LFS | — | ⚠️ | Kuota gratis 1 GB storage + 1 GB bandwidth → cepat habis kalau update sering |

**Rekomendasi:** JSONL per bulan (auto-commit) + SQLite di Releases (mis. mingguan, opsional).

**Isi tiap baris JSONL** (dari DB, satu sumber kebenaran):
```json
{"id_str":"...","member":"polka_lion","member_name":"高橋ポルカ@いきづらい部！",
 "created_at":"2025-03-14T12:56:00.000Z","text":"どうしよう…","text_id":"Gimana ya…",
 "favorite_count":2090,"conversation_count":46,"url":"https://x.com/polka_lion/status/...","media":null}
```
Plus `data/members.json` (metadata 10 member + warna resmi + sumber warna) dan `data/stats.json` (ringkasan).

**"Gak usah translate ulang"** → `tools/seed.py` diperluas supaya bisa `import` dari JSONL publik:
```bash
python -m tools.seed --from-jsonl data/tweets/    # isi DB + terjemahan, tanpa panggil API
```

---

## 2. GitHub Pages — apa yang bisa & tidak

| Komponen | Bisa di Pages? | Alasan |
|---|---|---|
| Worker (scrape + translate + Discord) | ❌ | Butuh proses berjalan 24/7 |
| API server (FastAPI) | ❌ | Pages hanya menyajikan file statis |
| Database SQLite | ❌ | Tidak ada server di Pages |
| **Viewer (React)** | ✅ | Kalau dibuild dengan **mode data statis** (baca JSONL, bukan `/api/*`) |

**Arsitektur target:**

```
[server rumah .151]  bot Docker (SUDAH JALAN)
        │  export (atomic write)
        ▼
  data/tweets/*.jsonl ──auto-commit──► GitHub (main)
        │                                   │
        └── Discord webhook                 ├─► Actions: build frontend + deploy Pages
                                            │        ▼
                                            │   https://wawiwuwawu.github.io/Ikizurai-Bu-tweet/
                                            └─► Releases: archive.db (opsional)
```

**Mode data statis di frontend** — perubahan kecil:
- `VITE_DATA_MODE=static` → `api.js` membaca `data/members.json` + `data/stats.json` + `data/tweets/<bulan>.jsonl` (lazy-load per bulan; total 1,28 MB tapi cukup muat 1-2 bulan pertama).
- Filter/pencarian dilakukan **client-side** (2.500 tweet = ringan; ke depan pakai index bulan).
- Keterbatasan jujur: tidak real-time (update mengikuti jadwal publish), tidak ada pencarian server-side.

**Dua varian viewer static:**
1. **Mirror (rekomendasi sekarang)** — bot tetap di server rumah; Pages hanya cermin data. Kerja: kecil, cepat.
2. **Serverless penuh (opsi masa depan)** — **GitHub Actions cron** menjalankan fetch+translate+export+commit; Discord webhook via Repository Secrets. Kelebihan: tanpa server, orang lain bisa fork & jalankan sendiri; kekurangan: cron Actions bisa telat (antrean), tanpa API server.

---

## 3. Rencana eksekusi (kalau disetujui)

### Fase 1 — Export (di kode bot)
- [ ] `app/export.py` — DB → `data/tweets/<YYYY-MM>.jsonl` + `data/members.json` + `data/stats.json`; **atomic write** (tmp → rename, biar git tidak pernah lihat file setengah jadi)
- [ ] CLI: `python -m app.worker --export`
- [ ] Opsi `EXPORT_ON_CYCLE=true` → ekspor otomatis di akhir siklus
- [ ] Tes: ekspor idempoten, urutan stabil (created_at,id_str), baris tidak berubah kalau data tidak berubah (diff-friendly)

### Fase 2 — Auto-publish ke GitHub
- [ ] `ops/publish.sh` — `git add data/ && commit "data: update <timestamp>" && push` **hanya kalau ada perubahan**
- [ ] Deploy key sudah ada (SSH sudah terpasang di repo); target repo ditulis di `.env` (`PUBLISH_REMOTE`), bukan di kode
- [ ] Jadwal: **harian** (bukan tiap 10 menit) supaya riwayat commit rapi → opsi `PUBLISH_INTERVAL_HOURS=24`

### Fase 3 — Pages viewer
- [ ] `frontend`: mode `VITE_DATA_MODE=static` + `base: '/Ikizurai-Bu-tweet/'`
- [ ] `.github/workflows/pages.yml` — build frontend + `actions/deploy-pages`
- [ ] Verifikasi: buka URL Pages → filter member, search, toggle JP/ID, pagination jalan tanpa API

### Fase 4 — Distribusi DB (opsional)
- [ ] Workflow rilis mingguan → attach `archive.db` + `tweets.jsonl` gabungan ke GitHub Releases

### Fase 5 — Dokumentasi & legal
- [ ] README: bagian "Pakai data ini" (seed dari JSONL, tanpa API key)
- [ ] `DISCLAIMER.md`: proyek fan non-komersial; hak tweet/karakter ada di pemegang hak; alamat kontak untuk takedown; terjemahan dibuat AI
- [ ] Pertimbangan lisensi data: kode tetap MIT; terjemahan/arsip bisa ditandai **CC BY-NC 4.0** atau "non-komersial, hubungi untuk penggunaan lain"

---

## 4. Risiko & hal yang perlu kamu putuskan

| # | Hal | Catatan |
|---|---|---|
| 1 | **Frekuensi publish** | Harian (rapi, hemat) vs tiap jam (lebih segar). Rekomendasi: harian. |
| 2 | **Custom domain** | `ikizulive.wawunime.my.id` diarahkan ke **Pages** (gratis, tanpa server rumah) atau tetap ke server rumah? Pages = lebih tahan mati lampu. |
| 3 | **Hak konten** | Mempublikasikan arsip + terjemahan = praktik umum fan-translation; wajib disclaimer + non-komersial + kontak takedown. Setuju? |
| 4 | **DB di Releases?** | Perlu untuk pengguna non-teknis; opsional tapi murah. |
| 5 | **Secrets di Actions** | Untuk varian serverless nanti: OmniRoute key + webhook disimpan sebagai Repository Secrets (terenkripsi, tidak pernah tampil di log). |
| 6 | **Repo bloat** | JSONL aman; **jangan** commit `.db`. Kalau nanti data > 5 MB, pindah ke branch `data` terpisah supaya `main` tetap ringan. |

---

## 5. Yang TIDAK berubah

- Bot tetap jalan di server rumah (Docker, port 8097) — Pages hanya *cermin* data.
- Database tetap SQLite sebagai satu-satunya sumber kebenaran; JSONL = hasil ekspor.
- Notifikasi Discord tetap dari bot.
