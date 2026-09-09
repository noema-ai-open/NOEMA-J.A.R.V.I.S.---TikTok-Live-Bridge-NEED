import asyncio
import time

import pytest

from app.resilient_service import LiveAIService
from app.settings import BridgeSettings, SettingsUpdate


@pytest.mark.asyncio
async def test_pending_music_is_released_automatically_when_interval_expires() -> None:
    service = LiveAIService(
        BridgeSettings(
            connect_on_start=False,
            interactive_music_enabled=True,
            music_backend="spotify",
            music_rotation_enabled=True,
            music_request_cooldown=5,
            spotify_enabled=True,
            spotify_client_id="client-id",
            spotify_refresh_token="refresh-token",
        )
    )
    scheduled: list[tuple[str, str | None]] = []
    service._schedule_spotify = lambda action, query=None: scheduled.append((str(action), query))  # type: ignore[method-assign]
    service._last_music_request_at = time.monotonic() - 6
    service._pending_music()["viewer-1"] = (
        "Daft Punk One More Time",
        False,
        "Viewer",
        "event-1",
    )

    task = asyncio.create_task(service._music_rotation_loop())
    try:
        await asyncio.sleep(0.6)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert scheduled == [("play", "Daft Punk One More Time")]
    assert service._pending_music() == {}


@pytest.mark.asyncio
async def test_rotation_off_makes_viewer_music_request_immediate() -> None:
    service = LiveAIService(
        BridgeSettings(
            connect_on_start=False,
            interactive_music_enabled=True,
            music_backend="spotify",
            music_rotation_enabled=False,
            music_request_cooldown=120,
            spotify_enabled=True,
            spotify_client_id="client-id",
            spotify_refresh_token="refresh-token",
        )
    )
    scheduled: list[tuple[str, str | None]] = []
    service._schedule_spotify = lambda action, query=None: scheduled.append((str(action), query))  # type: ignore[method-assign]
    service._last_music_request_at = time.monotonic()

    await service.add_mock_event(
        "chat_message",
        "Viewer",
        "/musik Stronger",
        "viewer-1",
    )
    await asyncio.sleep(0)

    assert scheduled == [("play", "Stronger")]
    assert service._pending_music() == {}


@pytest.mark.asyncio
async def test_turning_rotation_off_clears_stale_waiting_requests() -> None:
    service = LiveAIService(
        BridgeSettings(
            connect_on_start=False,
            interactive_music_enabled=True,
            music_rotation_enabled=True,
        )
    )
    service._pending_music()["viewer-1"] = (
        "Old request",
        False,
        "Viewer",
        "event-1",
    )

    payload = await service.update_settings(SettingsUpdate(music_rotation_enabled=False))

    assert payload["music_rotation_enabled"] is False
    assert service._pending_music() == {}
