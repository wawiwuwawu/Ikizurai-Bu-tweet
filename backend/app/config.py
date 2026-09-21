"""Konfigurasi aplikasi: baca .env + validasi.

Nilai dibaca saat instansiasi (default_factory) supaya bisa diuji/di-override.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        v = int(os.getenv(name, str(default)))
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return default if v is None else v.strip()


@dataclass
class Settings:
    # --- Sumber data ---
    source_base: str = field(default_factory=lambda: _str(
        "SOURCE_BASE", "https://gsm-app.com/lovelive/ikizulive-x-archive").rstrip("/"))
    check_interval_minutes: int = field(default_factory=lambda: _int("CHECK_INTERVAL_MINUTES", 10))

    # --- Discord ---
    discord_webhook_url: str = field(default_factory=lambda: _str("DISCORD_WEBHOOK_URL"))
    notify_without_translation: bool = field(default_factory=lambda: _bool("NOTIFY_WITHOUT_TRANSLATION", False))

    # --- Translasi (OmniRoute / OpenAI-compatible) ---
    omniroute_base_url: str = field(default_factory=lambda: _str(
        "OMNIROUTE_BASE_URL", "http://localhost:20128/v1").rstrip("/"))
    omniroute_api_key: str = field(default_factory=lambda: _str("OMNIROUTE_API_KEY"))
    translate_model: str = field(default_factory=lambda: _str("TRANSLATE_MODEL", "atria/Atria-Dawn-Preview"))
    translate_model_fallback: str = field(default_factory=lambda: _str("TRANSLATE_MODEL_FALLBACK"))
    translate_reasoning_effort: str = field(default_factory=lambda: _str("TRANSLATE_REASONING_EFFORT", "none"))
    translate_max_tokens: int = field(default_factory=lambda: _int("TRANSLATE_MAX_TOKENS", 2500))
    translate_batch_size: int = field(default_factory=lambda: _int("TRANSLATE_BATCH_SIZE", 5))
    translate_batch_per_cycle: int = field(default_factory=lambda: _int("TRANSLATE_BATCH_PER_CYCLE", 20))
    translate_max_attempts: int = field(default_factory=lambda: _int("TRANSLATE_MAX_ATTEMPTS", 8))
    translate_retry_backoff_min: int = field(default_factory=lambda: _int("TRANSLATE_RETRY_BACKOFF_MIN", 60))
    translate_retry_backoff_max: int = field(default_factory=lambda: _int("TRANSLATE_RETRY_BACKOFF_MAX", 900))
    translate_paused: bool = field(default_factory=lambda: _bool("TRANSLATE_PAUSED", False))

    # --- Ekspor dataset publik (JSON untuk GitHub Pages / dipakai ulang) ---
    export_dir: str = field(default_factory=lambda: _str(
        "EXPORT_DIR", str(BASE_DIR.parent / "dataset")))
    export_on_cycle: bool = field(default_factory=lambda: _bool("EXPORT_ON_CYCLE", True))

    # --- Web / runtime ---
    db_path: str = field(default_factory=lambda: _str("DB_PATH", str(BASE_DIR / "data" / "archive.db")))
    port: int = field(default_factory=lambda: _int("PORT", 8097))
    run_once: bool = field(default_factory=lambda: _bool("RUN_ONCE", False))
    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", False))
    backfill_on_start: bool = field(default_factory=lambda: _bool("BACKFILL_ON_START", True))
    worker_enabled: bool = field(default_factory=lambda: _bool("WORKER_ENABLED", True))
    log_level: str = field(default_factory=lambda: _str("LOG_LEVEL", "INFO").upper())

    errors: list[str] = field(default_factory=list)

    def validate(self, require_webhook: bool = True) -> list[str]:
        """Kembalikan daftar error konfigurasi (kosong = OK)."""
        self.errors = []
        if not self.source_base.startswith(("http://", "https://")):
            self.errors.append("SOURCE_BASE harus diawali http(s)://")
        if require_webhook and not self.discord_webhook_url:
            self.errors.append("DISCORD_WEBHOOK_URL belum diisi")
        if self.discord_webhook_url and not self.discord_webhook_url.startswith(
            "https://discord.com/api/webhooks/"
        ):
            self.errors.append("DISCORD_WEBHOOK_URL tidak valid (harus https://discord.com/api/webhooks/...)")
        if not self.omniroute_api_key:
            self.errors.append("OMNIROUTE_API_KEY belum diisi (translasi akan gagal)")
        return self.errors


def get_settings() -> Settings:
    return Settings()
