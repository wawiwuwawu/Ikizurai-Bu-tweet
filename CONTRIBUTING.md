# Kontribusi

Terima kasih sudah tertarik berkontribusi! 🐦

## Cara mulai

1. Fork repo & clone.
2. Setup dev: lihat bagian *Development* di [README](README.md).
3. Jalankan tes: `cd backend && .venv/bin/python -m pytest`
4. Buat branch: `git checkout -b fitur/singkat-jelas`
5. Commit dengan pesan jelas (conventional-ish: `feat:`, `fix:`, `docs:`, `test:`).
6. Buka Pull Request — jelaskan **apa** dan **kenapa**.

## Yang dicari

- Perbaikan kualitas prompt terjemahan (jelas & terukur, sertakan contoh).
- Dukungan filter/UX baru di web viewer.
- Perbaikan robustness scraper (mis. perubahan format sumber).
- Terjemahan dokumentasi (ID ⇄ EN).

## Aturan

- **Jangan commit** `.env`, API key, atau webhook URL.
- Sertakan tes untuk perubahan logika (backend `pytest`).
- Hormati rate limit sumber data & Discord: jangan menaikkan frekuensi default tanpa alasan.
