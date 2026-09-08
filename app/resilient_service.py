from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from app.llm import (
    LLMProvider,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderRequest,
    ProviderTimeout,
)
from app.models import JarvisState, QueuedQuestion, TikTokEvent
from app.music import MusicCommand, extract_music_request, parse_music_command
from app.service import LiveAIService as BaseLiveAIService
from app.spotify import SpotifyControl


_TRANSIENT_MARKERS = (
    "ConnectError",
    "ReadError",
    "WriteError",
    "RemoteProtocolError",
    "PoolTimeout",
)

_CLOUD_BACKUP_MODEL = "qwen/qwen3.7-flash"
_EXPLICIT_CHAT_COMMAND_COOLDOWN = 1.0


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


class FailoverProvider(LLMProvider):
    """Try providers in order, but only fail over before any public text was emitted."""

    def __init__(self, providers: tuple[LLMProvider, ...]) -> None:
        self.providers = providers

    async def generate(self, question: str) -> AsyncIterator[str]:
        failure: ProviderError | None = None
        for provider in self.providers:
            emitted = False
            try:
                async for chunk in provider.generate(question):
                    emitted = True
                    yield chunk
                return
            except ProviderError as exc:
                if emitted:
                    raise
                failure = exc
        raise failure or ProviderError("No LLM provider available")

    async def health(self) -> bool:
        for provider in self.providers:
            try:
                if await provider.health():
                    return True
            except ProviderError:
                continue
        return False


class LiveAIService(BaseLiveAIService):
    """Live service with retry, cloud model failover and strict media isolation."""

    def _cloud_backup_provider(self) -> LLMProvider | None:
        primary_model = self.settings.cloud_model.strip()
        if not primary_model or primary_model == _CLOUD_BACKUP_MODEL:
            return None

        request = self._provider_request("cloud")
        backup_request = ProviderRequest(
            base_url=request.base_url,
            api_key=request.api_key,
            model=_CLOUD_BACKUP_MODEL,
            temperature=request.temperature,
            context_length=request.context_length,
            max_output_tokens=request.max_output_tokens,
            stream=request.stream,
            reasoning=request.reasoning,
            timeout=request.timeout,
            system_prompt=request.system_prompt,
            http_referer=request.http_referer,
            x_title=request.x_title,
        )
        if self.provider_factory is not None:
            provider = self.provider_factory(backup_request)
        else:
            provider = OpenAICompatibleProvider(backup_request)
        return RetryingProvider(provider, attempts=2)

    def _provider(self, kind: str) -> LLMProvider:
        provider = RetryingProvider(
            super()._provider(kind), attempts=3 if kind == "cloud" else 2
        )
        if kind != "cloud":
            return provider

        backup = self._cloud_backup_provider()
        if backup is None:
            return provider
        return FailoverProvider((provider, backup))

    async def spotify_control(
        self, action: SpotifyControl, *, query: str | None = None
    ) -> dict[str, object]:
        """Normalize operator slash input and keep Spotify UI status coherent."""
        normalized_action: SpotifyControl = action
        normalized_query = query
        if action == "play" and query:
            command = parse_music_command(query)
            if command is not None and command.query:
                if command.action == "album":
                    normalized_action = "play_album"
                    normalized_query = command.query
                elif command.action == "request":
                    normalized_query = command.query

        playback = await super().spotify_control(
            normalized_action, query=normalized_query
        )
        return {
            "enabled": self.settings.spotify_enabled,
            "configured": bool(self.settings.spotify_client_id),
            **playback,
        }

    async def handle_event(
        self, event: TikTokEvent, *, allow_simulated: bool = False
    ) -> None:
        if event.metadata.get("simulated") is True and not allow_simulated:
            return

        if event.event_type != "chat_message" or not self.settings.interactive_music_enabled:
            await super().handle_event(event, allow_simulated=allow_simulated)
            return

        message = event.message or ""
        music_command = parse_music_command(message)
        extracted_request = extract_music_request(message)
        if music_command is None and extracted_request is None:
            await super().handle_event(event, allow_simulated=allow_simulated)
            return

        # Media commands are handled completely before the base chat router is
        # entered. This removes the old race where the question processor could
        # consume a natural-language music request before a later queue cleanup.
        await self._handle_media_event(event, music_command, extracted_request)

    async def _handle_media_event(
        self,
        event: TikTokEvent,
        music_command: MusicCommand | None,
        extracted_request: str | None,
    ) -> None:
        spotify_target = self.settings.music_backend == "spotify"
        query = (
            music_command.query
            if music_command is not None and music_command.action in {"request", "album"}
            else extracted_request
        )
        album_request = music_command is not None and music_command.action == "album"
        explicit_request = (
            music_command is not None
            and music_command.action in {"request", "album"}
            and bool(music_command.query)
        )
        ready = (
            self.settings.spotify_enabled
            and bool(self.settings.spotify_client_id)
            and self.settings.spotify_refresh_token is not None
            if spotify_target
            else self.settings.internet_enabled
            and self.settings.youtube_enabled
            and self.settings.brave_api_key is not None
        )
        now = time.monotonic()
        request_accepted = False
        control_accepted = False

        if explicit_request:
            last_request = getattr(
                self, "_last_explicit_music_request_at", float("-inf")
            )
            cooldown_elapsed = (
                now - last_request >= _EXPLICIT_CHAT_COMMAND_COOLDOWN
            )
        else:
            cooldown_elapsed = (
                now - self._last_music_request_at
                >= self.settings.music_request_cooldown
            )

        if (
            query
            and ready
            and cooldown_elapsed
            and (spotify_target or not album_request)
        ):
            request_accepted = True
            if explicit_request:
                self._last_explicit_music_request_at = now
            else:
                self._last_music_request_at = now
            event.metadata["music_request"] = query

        if (
            music_command is not None
            and music_command.action not in {"request", "album"}
            and (self.settings.spotify_enabled if spotify_target else self.settings.youtube_enabled)
            and now - self._last_music_control_at >= 2.0
        ):
            control_accepted = True
            self._last_music_control_at = now
            event.metadata["music_control"] = music_command.action

        record = event.model_dump(mode="json")
        record["is_question"] = False
        record["intent"] = "MEDIA"
        self.events.append(record)
        self.bus.publish({"type": "event", "event": record})

        if request_accepted and query:
            if spotify_target:
                self._schedule_spotify("play_album" if album_request else "play", query=query)
            else:
                self.bus.publish(
                    {
                        "type": "music_request",
                        "request": {
                            "query": query,
                            "display_name": event.user.display_name,
                            "event_id": event.event_id,
                        },
                    }
                )
            self._schedule_music_ack(available=True)
        elif query and not ready:
            self._schedule_music_ack(available=False)

        if control_accepted and music_command is not None:
            if spotify_target:
                self._schedule_spotify(music_command.action)
            else:
                self.bus.publish(
                    {
                        "type": "music_control",
                        "control": {
                            "action": music_command.action,
                            "display_name": event.user.display_name,
                            "event_id": event.event_id,
                        },
                    }
                )

        # A media command must never wake or pause the AI question processor.
        if self.current_question is None and self.state == JarvisState.LISTENING:
            self.state = JarvisState.IDLE
        self._publish_status()

    def _schedule_music_ack(self, *, available: bool) -> None:
        task = asyncio.create_task(
            self._speak_music_ack(available=available), name="music-ack"
        )
        self._media_tasks.add(task)
        task.add_done_callback(self._media_tasks.discard)

    async def _speak_music_ack(self, *, available: bool) -> None:
        text = (
            "Alles klar, der Musikwunsch ist angekommen."
            if available
            else "Die Musikfunktion ist gerade noch nicht bereit."
        )
        try:
            await self.tts.speak(text)
        except RuntimeError:
            # Music playback itself must remain independent from an optional
            # acknowledgement failure in the TTS bridge.
            return

    async def _answer(self, question: QueuedQuestion) -> None:
        await super()._answer(question)

        if not (self.paused and self.state == JarvisState.ERROR):
            return

        # Provider exhaustion in the base implementation requeues exactly the
        # failed question. Remove that one question and keep the live processor
        # available for later messages instead of forcing an operator click.
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
