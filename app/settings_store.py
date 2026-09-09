from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from app.settings import BridgeSettings


PERSISTED_FIELDS = {
    "tiktok_bridge_url",
    "provider",
    "llm_base_url",
    "llm_api_key",
    "model",
    "system_prompt",
    "temperature",
    "context_length",
    "max_output_tokens",
    "stream",
    "reasoning",
    "timeout",
    "cloud_fallback",
    "gift_grace_seconds",
    "cloud_base_url",
    "cloud_api_key",
    "cloud_model",
    "openrouter_http_referer",
    "openrouter_title",
    "memory_enabled",
    "memory_recent_turns",
    "memory_max_users_ram",
    "memory_max_turns_per_user_disk",
    "memory_retention_days",
    "internet_enabled",
    "brave_api_key",
    "search_timeout",
    "search_result_limit",
    "youtube_enabled",
    "interactive_music_enabled",
    "music_backend",
    "music_request_cooldown",
    "spotify_enabled",
    "spotify_client_id",
    "spotify_refresh_token",
}


def default_settings_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent / "runtime-settings.json"
    return Path(__file__).resolve().parent.parent / "runtime-settings.json"


class RuntimeSettingsStore:
    """Local JSON persistence. Secrets are intentionally stored as plain text."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_settings_path()

    def load(self, base: BridgeSettings) -> BridgeSettings:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return base
            allowed = {key: value for key, value in payload.items() if key in PERSISTED_FIELDS}
            # 0.6 migration: 30 seconds was the old default and caused rapid
            # song replacement in busy TikTok chats. Preserve custom values,
            # but move the legacy default to the new five-minute rotation.
            if allowed.get("music_request_cooldown") in {30, 30.0}:
                allowed["music_request_cooldown"] = 300.0
            merged = base.model_dump()
            merged.update(allowed)
            return BridgeSettings.model_validate(merged)
        except (OSError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
            return base

    def save(self, settings: BridgeSettings) -> None:
        payload = settings.model_dump(include=PERSISTED_FIELDS)
        for key in (
            "llm_api_key",
            "cloud_api_key",
            "brave_api_key",
            "spotify_refresh_token",
        ):
            secret = getattr(settings, key)
            payload[key] = secret.get_secret_value() if secret is not None else None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
