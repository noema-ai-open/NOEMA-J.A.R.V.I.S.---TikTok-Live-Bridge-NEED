from datetime import timezone

import pytest
from pydantic import ValidationError

from app.models import TikTokEvent
from app.settings import BridgeSettings


def test_parses_tiktok_bridge_event_schema() -> None:
    event = TikTokEvent.from_websocket_payload(
        {
            "platform": "tiktok",
            "event_type": "gift",
            "event_id": "gift-1",
            "timestamp": "2026-08-08T12:00:00Z",
            "user": {"display_name": "Fan", "user_id": "42"},
            "metadata": {"gift_name": "Rose", "repeat_count": 3},
        }
    )
    assert event.event_type == "gift"
    assert event.timestamp.tzinfo == timezone.utc
    assert event.metadata["repeat_count"] == 3


def test_ignores_blocked_and_unneeded_bridge_events() -> None:
    assert TikTokEvent.from_websocket_payload({"type": "blocked", "event": {}}) is None
    assert TikTokEvent.from_websocket_payload({"event_type": "like"}) is None


def test_settings_validation_and_secret_redaction() -> None:
    settings = BridgeSettings(
        llm_api_key="secret",
        brave_api_key="search-secret",
        spotify_refresh_token="spotify-secret",
        model="model-id",
    )
    public = settings.public_payload()
    assert public["llm_api_key_configured"] is True
    assert public["brave_api_key_configured"] is True
    assert "secret" not in str(public)
    assert "search-secret" not in str(public)
    assert "spotify-secret" not in str(public)
    assert public["spotify_connected"] is True
    assert public["reasoning"] is False
    assert public["stream"] is True
    assert public["context_length"] == 8192
    assert public["gift_grace_seconds"] == 0.75
    assert public["internet_enabled"] is False
    assert public["youtube_enabled"] is False
    assert public["interactive_music_enabled"] is False
    assert public["music_backend"] == "youtube"
    assert public["music_request_cooldown"] == 30.0

    with pytest.raises(ValidationError):
        BridgeSettings(tiktok_bridge_url="not-a-url")
    with pytest.raises(ValidationError):
        BridgeSettings(max_output_tokens=0)
    with pytest.raises(ValidationError):
        BridgeSettings(search_result_limit=0)
    with pytest.raises(ValidationError):
        BridgeSettings(music_request_cooldown=1)
