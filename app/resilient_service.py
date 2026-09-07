from __future__ import annotations

from app.models import JarvisState, QueuedQuestion, TikTokEvent
from app.music import extract_music_request, parse_music_command
from app.service import LiveAIService as BaseLiveAIService


class LiveAIService(BaseLiveAIService):
    """Live service with non-blocking recovery and strict media isolation."""

    async def handle_event(
        self, event: TikTokEvent, *, allow_simulated: bool = False
    ) -> None:
        is_viewer_media_command = False
        if event.event_type == "chat_message" and self.settings.interactive_music_enabled:
            message = event.message or ""
            is_viewer_media_command = (
                parse_music_command(message) is not None
                or extract_music_request(message) is not None
            )

        await super().handle_event(event, allow_simulated=allow_simulated)

        # The base service currently queues natural-language play requests for
        # the LLM after also publishing them to the media layer. During a live
        # show that can make one viewer music request start/fail the AI path and
        # leave the operator seeing a pause. Media commands are side effects,
        # not AI questions, so remove only this event from the AI queue before
        # the processor can consume the wake-up.
        if not is_viewer_media_command:
            return

        before = len(self.questions._items)
        self.questions._items[:] = [
            item for item in self.questions._items if item.event_id != event.event_id
        ]
        if len(self.questions._items) == before:
            return

        if self.current_question is None and self.state == JarvisState.LISTENING:
            self.state = JarvisState.IDLE
        self.bus.publish({"type": "queue", "queue": self.queue_payload()})
        self._publish_status()

    async def _answer(self, question: QueuedQuestion) -> None:
        await super()._answer(question)

        if not (self.paused and self.state == JarvisState.ERROR):
            return

        # Provider exhaustion in the base implementation requeues exactly the
        # question that just failed. Runtime errors and manual pause do not.
        before = len(self.questions._items)
        self.questions._items[:] = [
            item for item in self.questions._items if item.event_id != question.event_id
        ]
        if len(self.questions._items) == before:
            return

        self.paused = False
        self.state = JarvisState.LISTENING if len(self.questions) else JarvisState.IDLE
        self.bus.publish({"type": "queue", "queue": self.queue_payload()})
        if len(self.questions):
            self._wake.set()
        self._publish_status()
