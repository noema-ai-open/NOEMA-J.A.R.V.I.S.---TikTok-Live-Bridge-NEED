from datetime import datetime, timedelta, timezone

import pytest

from app.models import EventUser, TikTokEvent


@pytest.fixture(autouse=True)
def isolated_default_memory(tmp_path, monkeypatch):
    monkeypatch.setattr("app.memory.default_memory_root", lambda: tmp_path / "memory")


@pytest.fixture
def event_factory():
    sequence = 0

    def make(
        *,
        event_type: str = "chat_message",
        user_id: str = "user-1",
        display_name: str = "Viewer",
        message: str | None = "Wie heißt das Spiel?",
        metadata: dict[str, object] | None = None,
    ) -> TikTokEvent:
        nonlocal sequence
        sequence += 1
        return TikTokEvent(
            event_type=event_type,
            event_id=f"event-{sequence}",
            timestamp=datetime(2026, 8, 8, tzinfo=timezone.utc) + timedelta(seconds=sequence),
            user=EventUser(display_name=display_name, user_id=user_id),
            message=message if event_type == "chat_message" else None,
            metadata=metadata or {},
        )

    return make
