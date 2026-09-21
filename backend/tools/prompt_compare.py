"""Alat dev: uji cepat prompt translasi pada sampel tweet nyata dari DB.

Pakai:
    python tools/prompt_compare.py              # pakai prompt produksi (app.translate.SYSTEM_PROMPT)
    python tools/prompt_compare.py prompt.txt   # pakai prompt dari file (untuk eksperimen)

Output: JP + hasil terjemahan per tweet ke stdout (tanpa mengubah database).
"""
import json
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
sys.path.insert(0, str(BASE_DIR))

from app.config import get_settings  # noqa: E402
from app.translate import SYSTEM_PROMPT, parse_batch_json  # noqa: E402
from app import db as dbm  # noqa: E402

BATCH = 5
N_SAMPLE = 10


def main() -> int:
    settings = get_settings()
    prompt = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else SYSTEM_PROMPT

    conn = dbm.connect(settings.db_path)
    rows = conn.execute(
        "SELECT id_str, member, text, text_id FROM tweets "
        "ORDER BY created_at DESC LIMIT ?", (N_SAMPLE,)
    ).fetchall()
    tweets = [{"id_str": r["id_str"], "text": r["text"]} for r in rows]

    total = 0
    for i in range(0, len(tweets), BATCH):
        batch = tweets[i:i + BATCH]
        user = "\n".join(json.dumps(t, ensure_ascii=False) for t in batch)
        payload = {
            "model": settings.translate_model,
            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
            "temperature": 0.5,
            "max_tokens": settings.translate_max_tokens,
            "reasoning_effort": settings.translate_reasoning_effort or None,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        t0 = time.time()
        p = subprocess.run(
            ["curl", "-s", "--max-time", "180", "-X", "POST",
             f"{settings.omniroute_base_url}/chat/completions",
             "-H", f"Authorization: Bearer {settings.omniroute_api_key}",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload, ensure_ascii=False)],
            capture_output=True, text=True, timeout=200,
        )
        lat = time.time() - t0
        try:
            content = json.loads(p.stdout)["choices"][0]["message"].get("content") or ""
        except (ValueError, KeyError, IndexError):
            print(f"  batch {i//BATCH+1}: GAGAL ({p.stdout[:120]})")
            continue
        parsed = parse_batch_json(content, [t["id_str"] for t in batch])
        total += len(parsed)
        print(f"  batch {i//BATCH+1}: {lat:.1f}s parsed {len(parsed)}/{len(batch)}")
        for t in batch:
            print("-" * 80)
            print("JP:", t["text"].replace("\n", " / ")[:150])
            print("ID:", str(parsed.get(t["id_str"], "<kosong>")).replace("\n", " / ")[:220])
    print(f"\nTotal: {total}/{len(tweets)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
