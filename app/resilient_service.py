from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.llm import LLMProvider, ProviderError, ProviderTimeout
from app.models import JarvisState, QueuedQuestion, TikTokEvent
from app.music import extract_music_request, parse_music_command
from app.service import LiveAIService as BaseLiveAIService


_TRANSIENT_MARKERS = (
    "ConnectError",
    "ReadError",
    "WriteError",
    "RemoteProtocolError",
    "PoolTimeout",
)


def _is_transient_provider_error(exc: ProviderError) -> bool:
    return isinstance(exc, ProviderTimeout) or any(
        marker in str(exc) for marker in _TRANSIENT_MARKERS
    )


class RetryingProvider(LLMProvider):
    """Retry short-lived transport failures before provider failover.

    Retries are only attempted before the provider has emitted any text, so a
    broken stream can never duplicate already-visible answer chunks.
    """

    def __init__(self, provider: LLMProvider, *, attempts: int = 3) -> None:
        self.provider = provider
        self.attempts = max(1, attempts)

    async def generate(self, question: str) -> AsyncIterator[str]:
        for attempt in range(self.attempts):
            emitted = False
            try:
                async for chunk in self.provider.generate(question):
                    emitted = True
                    yield chunk
                return
            except ProviderError as exc:
                if emitted or not _is_transient_provider_error(exc) or attempt + 1 >= self.attempts:
                    raise
                await asyncio.sleep(0.25 * (attempt + 1))

    async def health(self) -> bool:
        try:
            return await self.provider.health()
        except ProviderError:
            return False


class LiveAIService(BaseLiveAIService):
    """Live service with non-blocking recovery and strict media isolation."""

    def _provider(self, kind: str) -> LLMProvider:
        provider = super()._provider(kind)
        return RetryingProvider(provider, attempts=3 if kind == "cloud" else 2)

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
