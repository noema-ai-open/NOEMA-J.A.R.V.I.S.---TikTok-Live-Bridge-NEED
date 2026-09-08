from __future__ import annotations

import os
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.prompts import DEFAULT_SYSTEM_PROMPT


class BridgeSettings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    host: str = "127.0.0.1"
    port: int = Field(default=8770, ge=1, le=65535)
    tiktok_bridge_url: str = "http://127.0.0.1:8765"
    provider: Literal["local", "cloud"] = "local"
    llm_base_url: str = "http://127.0.0.1:1234/v1"
    llm_api_key: SecretStr | None = None
    model: str = ""
    system_prompt: str = Field(default=DEFAULT_SYSTEM_PROMPT, min_length=1, max_length=8000)
    temperature: float = Field(default=0.6, ge=0, le=2)
    context_length: int = Field(default=8192, ge=512, le=131072)
    max_output_tokens: int = Field(default=800, ge=1, le=4096)
    stream: bool = True
    reasoning: bool = False
    timeout: float = Field(default=20.0, gt=0, le=300)
    cloud_fallback: bool = True
    cloud_base_url: str = "https://openrouter.ai/api/v1"
    cloud_api_key: SecretStr | None = None
    cloud_model: str = "qwen/qwen3.7-flash"
    openrouter_http_referer: str = ""
    openrouter_title: str = "NOEMA J.A.R.V.I.S."
    memory_enabled: bool = True
    memory_recent_turns: int = Field(default=16, ge=1, le=20)
    memory_max_users_ram: int = Field(default=200, ge=1, le=5000)
    memory_max_turns_per_user_disk: int = Field(default=100, ge=1, le=1000)
    memory_retention_days: int = Field(default=30, ge=0, le=3650)
    internet_enabled: bool = False
    brave_api_key: SecretStr | None = None
    search_timeout: float = Field(default=8.0, gt=0, le=30)
    search_result_limit: int = Field(default=4, ge=1, le=10)
    youtube_enabled: bool = False
    interactive_music_enabled: bool = False
    music_backend: Literal["youtube", "spotify"] = "youtube"
    music_request_cooldown: float = Field(default=30.0, ge=5, le=300)
    spotify_enabled: bool = False
    spotify_client_id: str = Field(default="", max_length=200)
    spotify_refresh_token: SecretStr | None = None
    queue_max_size: int = Field(default=100, ge=1, le=1000)
    gift_grace_seconds: float = Field(default=0.75, ge=0, le=5)
    reconnect_initial_seconds: float = Field(default=1.0, gt=0, le=60)
    reconnect_max_seconds: float = Field(default=30.0, gt=0, le=300)
    connect_on_start: bool = True

    @field_validator("tiktok_bridge_url", "llm_base_url", "cloud_base_url")
    @classmethod
    def valid_http_url(cls, value: str) -> str:
        cleaned = value.strip().rstrip("/")
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an absolute http(s) URL")
        return cleaned

    @field_validator("system_prompt")
    @classmethod
    def valid_system_prompt(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("system_prompt must not be empty")
        return cleaned

    @property
    def tiktok_websocket_url(self) -> str:
        scheme = "wss" if self.tiktok_bridge_url.startswith("https://") else "ws"
        rest = self.tiktok_bridge_url.split("://", 1)[1]
        return f"{scheme}://{rest}/ws/events"

    @classmethod
    def from_environment(cls) -> "BridgeSettings":
        values: dict[str, object] = {}
        mapping = {
            "NOEMA_HOST": "host",
            "NOEMA_PORT": "port",
            "NOEMA_TIKTOK_BRIDGE_URL": "tiktok_bridge_url",
            "NOEMA_LLM_BASE_URL": "llm_base_url",
            "NOEMA_LLM_MODEL": "model",
            "NOEMA_LLM_API_KEY": "llm_api_key",
            "NOEMA_INTERNET_ENABLED": "internet_enabled",
            "NOEMA_BRAVE_API_KEY": "brave_api_key",
            "NOEMA_YOUTUBE_ENABLED": "youtube_enabled",
            "NOEMA_INTERACTIVE_MUSIC_ENABLED": "interactive_music_enabled",
            "NOEMA_SPOTIFY_CLIENT_ID": "spotify_client_id",
        }
        for env_name, field_name in mapping.items():
            value = os.getenv(env_name)
            if value:
                values[field_name] = value
        return cls.model_validate(values)

    def public_payload(self) -> dict[str, object]:
        return {
            "tiktok_bridge_url": self.tiktok_bridge_url,
            "provider": self.provider,
            "llm_base_url": self.llm_base_url,
            "model": self.model,
            "system_prompt": self.system_prompt,
            "temperature": self.temperature,
            "context_length": self.context_length,
            "max_output_tokens": self.max_output_tokens,
            "stream": self.stream,
            "reasoning": self.reasoning,
            "timeout": self.timeout,
            "cloud_fallback": self.cloud_fallback,
            "gift_grace_seconds": self.gift_grace_seconds,
            "cloud_base_url": self.cloud_base_url,
            "cloud_model": self.cloud_model,
            "openrouter_http_referer": self.openrouter_http_referer,
            "openrouter_title": self.openrouter_title,
            "memory_enabled": self.memory_enabled,
            "memory_recent_turns": self.memory_recent_turns,
            "memory_max_users_ram": self.memory_max_users_ram,
            "memory_max_turns_per_user_disk": self.memory_max_turns_per_user_disk,
            "memory_retention_days": self.memory_retention_days,
            "llm_api_key_configured": self.llm_api_key is not None,
            "cloud_api_key_configured": self.cloud_api_key is not None,
            "internet_enabled": self.internet_enabled,
            "brave_api_key_configured": self.brave_api_key is not None,
            "search_timeout": self.search_timeout,
            "search_result_limit": self.search_result_limit,
            "youtube_enabled": self.youtube_enabled,
            "interactive_music_enabled": self.interactive_music_enabled,
            "music_backend": self.music_backend,
            "music_request_cooldown": self.music_request_cooldown,
            "spotify_enabled": self.spotify_enabled,
            "spotify_client_id": self.spotify_client_id,
            "spotify_connected": self.spotify_refresh_token is not None,
        }


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tiktok_bridge_url: str | None = None
    provider: Literal["local", "cloud"] | None = None
    llm_base_url: str | None = None
    llm_api_key: str | None = Field(default=None, max_length=1000)
    model: str | None = Field(default=None, max_length=300)
    system_prompt: str | None = Field(default=None, min_length=1, max_length=8000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    context_length: int | None = Field(default=None, ge=512, le=131072)
    max_output_tokens: int | None = Field(default=None, ge=1, le=4096)
    stream: bool | None = None
    reasoning: bool | None = None
    timeout: float | None = Field(default=None, gt=0, le=300)
    cloud_fallback: bool | None = None
    gift_grace_seconds: float | None = Field(default=None, ge=0, le=5)
    cloud_base_url: str | None = None
    cloud_api_key: str | None = Field(default=None, max_length=1000)
    cloud_model: str | None = Field(default=None, max_length=300)
    openrouter_http_referer: str | None = Field(default=None, max_length=500)
    openrouter_title: str | None = Field(default=None, max_length=200)
    memory_enabled: bool | None = None
    memory_recent_turns: int | None = Field(default=None, ge=1, le=20)
    memory_max_users_ram: int | None = Field(default=None, ge=1, le=5000)
    memory_max_turns_per_user_disk: int | None = Field(default=None, ge=1, le=1000)
    memory_retention_days: int | None = Field(default=None, ge=0, le=3650)
    internet_enabled: bool | None = None
    brave_api_key: str | None = Field(default=None, max_length=1000)
    search_timeout: float | None = Field(default=None, gt=0, le=30)
    search_result_limit: int | None = Field(default=None, ge=1, le=10)
    youtube_enabled: bool | None = None
    interactive_music_enabled: bool | None = None
    music_backend: Literal["youtube", "spotify"] | None = None
    music_request_cooldown: float | None = Field(default=None, ge=5, le=300)
    spotify_enabled: bool | None = None
    spotify_client_id: str | None = Field(default=None, max_length=200)
