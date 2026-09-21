#!/usr/bin/env bash
# Publish dataset publik ke GitHub — commit + push HANYA bila ada perubahan.
#
# Dipakai oleh cron (lihat `crontab -l`) atau manual:
#   ./ops/publish.sh            # commit + push kalau ada perubahan
#   ./ops/publish.sh --dry-run  # lihat apa yang akan di-commit
#
# Aman dijalankan berulang: kalau dataset tidak berubah, tidak ada commit baru.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"
DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

log() { printf '[publish] %s\n' "$*"; }

if [[ ! -d dataset ]]; then
  log "ERROR: folder dataset/ tidak ada — jalankan ekspor dulu (docker exec ikizurai-bu-tweet python -m app.worker --export)"
  exit 1
fi

# 1) pastikan tidak ada file sementara yang tertinggal
find dataset -name '*.tmp' -delete 2>/dev/null || true

# 2) ada perubahan?
if git diff --quiet -- dataset && git diff --cached --quiet -- dataset \
   && [[ -z "$(git ls-files --others --exclude-standard dataset)" ]]; then
  log "tidak ada perubahan dataset — tidak ada yang di-push"
  exit 0
fi

log "perubahan terdeteksi:"
git status --short dataset | head -20

if [[ $DRY_RUN -eq 1 ]]; then
  log "dry-run: berhenti di sini"
  exit 0
fi

# 3) commit + push
git add dataset
STAMP="$(TZ=Asia/Jakarta date '+%Y-%m-%d %H:%M WIB')"
git -c user.name="ikizurai-bu-bot" -c user.email="bot@users.noreply.github.com" \
    commit -q -m "data: perbarui dataset publik (${STAMP})" -- dataset
git push -q origin HEAD
log "selesai — $(git log -1 --format='%h %s')"
