#!/usr/bin/env bash
# Publish dataset begitu backfill translasi SELESAI — lalu terus menjaga mirror
# tetap segar (publish.sh hanya commit bila dataset berubah, jadi aman diulang).
#
# Dipasang di cron (mis. tiap 15 menit). Keluar tanpa melakukan apa pun selama
# translasi belum tuntas, supaya riwayat commit tidak penuh progres setengah jadi.
set -euo pipefail

cd "$(dirname "$0")/.."
STATS_URL="${STATS_URL:-http://127.0.0.1:8097/api/stats}"

stats="$(curl -fsS --max-time 10 "$STATS_URL" 2>/dev/null || true)"
if [[ -z "$stats" ]]; then
  echo "[publish-when-done] API lokal tidak terjangkau ($STATS_URL) — lewati"
  exit 0
fi

read -r translated total <<<"$(printf '%s' "$stats" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print(d.get("translated", 0), d.get("total", 0))
')"

if [[ "$total" -eq 0 ]]; then
  echo "[publish-when-done] belum ada tweet — lewati"
  exit 0
fi

if [[ "$translated" -lt "$total" ]]; then
  echo "[publish-when-done] translasi belum selesai: ${translated}/${total} — tunggu"
  exit 0
fi

echo "[publish-when-done] translasi SELESAI (${translated}/${total}) → publish"
exec ./ops/publish.sh
