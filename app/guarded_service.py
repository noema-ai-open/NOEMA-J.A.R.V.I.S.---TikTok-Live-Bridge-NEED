from __future__ import annotations

import time

from app.models import TikTokEvent
from app.music import MusicCommand
from app.resilient_service import LiveAIService as ResilientLiveAIService


_USER_MUSIC_COMMAND_COOLDOWN_SECONDS = 20.0


class LiveAIService(ResilientLiveAIService):
    """Resilient live service with per-viewer music abuse protection.

    Rotation already keeps at most one pending request per viewer. This layer
    prevents a viewer from continuously replacing that slot or hammering the
    player when rotation is disabled. Gift priority always wins immediately.
    """

    def _last_music_command_by_user(self) -> dict[str, float]:
        seen = getattr(self, "_music_command_seen_by_user", None)
        if seen is None:
            seen = {}
            self._music_command_seen_by_user = seen
        return seen

    async def _handle_media_event(
        self,
        event: TikTokEvent,
        music_command: MusicCommand | None,
        extracted_request: str | None,
    ) -> None:
        query = (
            music_command.query
            if music_command is not None and music_command.action in {"request", "album"}
            else extracted_request
        )
        if not query:
            await super()._handle_media_event(event, music_command, extracted_request)
            return

        now = time.monotonic()
        user_id = event.user.user_id
        rotation_enabled = self.settings.music_rotation_enabled
        gift_priority = rotation_enabled and self._gift_priority().get(user_id, 0.0) >= now
        pending = self._pending_music()
        seen = self._last_music_command_by_user()

        # A viewer gets one waiting slot. Repeated /musik commands no longer
        # replace the queued title and therefore cannot keep reshuffling the
        # FIFO queue. A gift priority bypass is deliberately exempt.
        if rotation_enabled and user_id in pending and not gift_priority:
            self._record_ignored_music_request(event, query, "already_pending")
            return

        # Also throttle accepted/direct requests per viewer. This matters most
        # when rotation is disabled, where the global rotation cooldown no
        # longer protects the player from command spam.
        last_seen = seen.get(user_id, float("-inf"))
        if not gift_priority and now - last_seen < _USER_MUSIC_COMMAND_COOLDOWN_SECONDS:
            self._record_ignored_music_request(event, query, "user_cooldown")
            return

        seen[user_id] = now
        await super()._handle_media_event(event, music_command, extracted_request)

    def _record_ignored_music_request(
        self, event: TikTokEvent, query: str, reason: str
    ) -> None:
        event.metadata["music_request_ignored"] = query
        event.metadata["music_request_ignored_reason"] = reason
        record = event.model_dump(mode="json")
        record["is_question"] = False
        record["intent"] = "MEDIA"
        self.events.append(record)
        self.bus.publish({"type": "event", "event": record})
        self._publish_status()
