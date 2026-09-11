from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.clients import TTSClient, TikTokBridgeClient
from app.chat_router import INTENT_PRIORITY, ChatIntent, route_chat
from app.llm import (
    LMStudioProvider,
    LLMProvider,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderRequest,
    build_question_prompt,
    validate_public_output,
)
from app.memory import ConversationTurn, MemoryManager
from app.models import EventUser, GiftInfo, JarvisState, QueuedQuestion, TikTokEvent
from app.music import extract_music_request, parse_music_command
from app.priority_queue import QuestionQueue
from app.provider_chain import provider_order
from app.question_detection import is_question
from app.search import (
    BraveSearchClient,
    SearchError,
    SearchKind,
    SearchResult,
    build_search_context,
    needs_internet_search,
    requested_search_kind,
)
from app.settings import BridgeSettings, SettingsUpdate
from app.settings_store import RuntimeSettingsStore
from app.spotify import (
    SpotifyConnectClient,
    SpotifyControl,
    SpotifyError,
    create_oauth_request,
)


class DashboardBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, message: dict[str, Any]) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(message)


ProviderFactory = Callable[[ProviderRequest], LLMProvider]
SearchFactory = Callable[[str, float], BraveSearchClient]
SpotifyFactory = Callable[[str, str | None, float], SpotifyConnectClient]


class LiveAIService:
    def __init__(
        self,
        settings: BridgeSettings,
        *,
        provider_factory: ProviderFactory | None = None,
        search_factory: SearchFactory | None = None,
        spotify_factory: SpotifyFactory | None = None,
        settings_store: RuntimeSettingsStore | None = None,
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.settings = settings
        self.provider_factory = provider_factory
        self.search_factory = search_factory
        self.spotify_factory = spotify_factory
        self.settings_store = settings_store
        self.questions = QuestionQueue(max_size=settings.queue_max_size)
        self.events: deque[dict[str, Any]] = deque(maxlen=300)
        self.memory = memory_manager or MemoryManager(
            enabled=settings.memory_enabled,
            recent_turns=settings.memory_recent_turns,
            max_users_ram=settings.memory_max_users_ram,
            max_turns_per_user_disk=settings.memory_max_turns_per_user_disk,
            retention_days=settings.memory_retention_days,
        )
        self.bus = DashboardBus()
        self.state = JarvisState.IDLE
        self.bridge_connected = False
        self.llm_connected = False
        self.tts_speaking = False
        self.paused = False
        self.current_question: QueuedQuestion | None = None
        self.current_answer = ""
        self.last_answer = ""
        self.last_latency_ms: int | None = None
        self.last_error: str | None = None
        self.internet_connected = False
        self.last_search_error: str | None = None
        self.spotify_connected = False
        self.spotify_playback: dict[str, object] = {}
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._connector: TikTokBridgeClient | None = None
        self._connector_task: asyncio.Task[None] | None = None
        self._generation_task: asyncio.Task[None] | None = None
        self._media_tasks: set[asyncio.Task[None]] = set()
        self._spotify_oauth: dict[str, tuple[str, float]] = {}
        self._spotify_client_instance: SpotifyConnectClient | None = None
        self._spotify_client_config: tuple[str, str | None] | None = None
        self._stopping = False
        self._speaking_until = 0.0
        self._last_music_request_at = float("-inf")
        self._last_music_control_at = float("-inf")
        self.tts = TTSClient(settings.tiktok_bridge_url)

    async def start(self) -> None:
        self._stopping = False
        await self.memory.start()
        self._tasks = [
            asyncio.create_task(self._processor(), name="question-processor"),
            asyncio.create_task(self._monitor(), name="dependency-monitor"),
        ]
        if self.settings.connect_on_start:
            await self._start_connector()

    async def stop(self) -> None:
        self._stopping = True
        if self._connector is not None:
            await self._connector.stop()
        tasks = [*self._tasks]
        if self._connector_task is not None:
            tasks.append(self._connector_task)
        if self._generation_task is not None:
            tasks.append(self._generation_task)
        tasks.extend(self._media_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.memory.close()
        self._tasks.clear()
        self._connector_task = None
        self._generation_task = None
        self._media_tasks.clear()

    async def _start_connector(self) -> None:
        self._connector = TikTokBridgeClient(
            self.settings.tiktok_websocket_url,
            self.handle_event,
            self._connection_changed,
            initial_delay=self.settings.reconnect_initial_seconds,
            maximum_delay=self.settings.reconnect_max_seconds,
        )
        self._connector_task = asyncio.create_task(
            self._connector.run(), name="tiktok-bridge-websocket"
        )

    async def _restart_connector(self) -> None:
        if not self.settings.connect_on_start:
            return
        old_connector = self._connector
        old_task = self._connector_task
        if old_connector is not None:
            await old_connector.stop()
        if old_task is not None:
            old_task.cancel()
            await asyncio.gather(old_task, return_exceptions=True)
        self.bridge_connected = False
        await self._start_connector()

    async def _connection_changed(self, connected: bool, error: str | None) -> None:
        self.bridge_connected = connected
        if connected:
            if self.last_error and self.last_error.startswith("TikTok Bridge"):
                self.last_error = None
        elif error:
            self.last_error = error
        self._publish_status()

    async def handle_event(
        self, event: TikTokEvent, *, allow_simulated: bool = False
    ) -> None:
        if event.metadata.get("simulated") is True and not allow_simulated:
            return
        chat_message = event.event_type == "chat_message"
        intent = ChatIntent.NOISE
        if chat_message:
            preliminary = route_chat(event.message or "")
            has_history = False
            if preliminary is not ChatIntent.NOISE and self.settings.memory_enabled:
                has_history = await self.memory.has_history(
                    event.user.user_id, event.user.display_name
                )
            intent = route_chat(event.message or "", has_user_history=has_history)
        question = intent in {
            ChatIntent.DIRECT_COMMAND,
            ChatIntent.DIRECT_QUESTION,
            ChatIntent.FOLLOW_UP,
            ChatIntent.GENERAL_QUESTION,
        }
        music_request: dict[str, str] | None = None
        music_request_kind = "track"
        music_control: dict[str, str] | None = None
        music_command = parse_music_command(event.message or "") if chat_message else None
        music_command_handled = music_command is not None and self.settings.interactive_music_enabled
        if chat_message and self.settings.interactive_music_enabled:
            query = (
                music_command.query
                if music_command is not None
                and music_command.action in {"request", "album"}
                else extract_music_request(event.message or "")
            )
            spotify_target = self.settings.music_backend == "spotify"
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
            cooldown_elapsed = (
                now - self._last_music_request_at
                >= self.settings.music_request_cooldown
            )
            album_request = music_command is not None and music_command.action == "album"
            if query and ready and cooldown_elapsed and (spotify_target or not album_request):
                self._last_music_request_at = now
                event.metadata["music_request"] = query
                music_request_kind = "album" if album_request else "track"
                music_request = {
                    "query": query,
                    "display_name": event.user.display_name,
                    "event_id": event.event_id,
                }
            if (
                music_command is not None
                and music_command.action not in {"request", "album"}
                and (
                    self.settings.spotify_enabled
                    if spotify_target
                    else self.settings.youtube_enabled
                )
                and now - self._last_music_control_at >= 2.0
            ):
                self._last_music_control_at = now
                event.metadata["music_control"] = music_command.action
                music_control = {
                    "action": music_command.action,
                    "display_name": event.user.display_name,
                    "event_id": event.event_id,
                }
        record = event.model_dump(mode="json")
        record["is_question"] = question
        record["intent"] = intent.value if chat_message else None
        if event.event_type == "gift":
            record["gift_tier"] = GiftInfo.from_event(event).tier
        self.events.append(record)
        self.bus.publish({"type": "event", "event": record})
        if music_request is not None:
            if self.settings.music_backend == "spotify":
                action = "play_album" if music_request_kind == "album" else "play"
                self._schedule_spotify(action, query=music_request["query"])
            else:
                self.bus.publish({"type": "music_request", "request": music_request})
        if music_control is not None:
            if self.settings.music_backend == "spotify":
                self._schedule_spotify(music_control["action"])
            else:
                self.bus.publish({"type": "music_control", "control": music_control})

        if event.event_type == "gift":
            boosted = self.questions.boost_for_gift(event)
            if boosted is not None:
                self.bus.publish({"type": "queue", "queue": self.queue_payload()})
        elif chat_message and not music_command_handled and intent is not ChatIntent.NOISE:
            queued = self.questions.add(
                event,
                is_question=question,
                priority=INTENT_PRIORITY[intent],
                priority_reason=f"intent:{intent.value.lower()}",
                intent=intent.value,
            )
            if queued is None:
                self.last_error = "Chat queue is full"
                self.state = JarvisState.ERROR
            else:
                if self.state == JarvisState.IDLE:
                    self.state = JarvisState.LISTENING
                self._wake.set()
                self.bus.publish({"type": "queue", "queue": self.queue_payload()})
        self._publish_status()

    async def add_mock_event(
        self,
        event_type: str,
        display_name: str,
        message: str | None = None,
        user_id: str | None = None,
        gift_name: str | None = None,
        repeat_count: int = 1,
        diamond_count: int = 1,
    ) -> TikTokEvent:
        metadata: dict[str, object] = {"simulated": True}
        if event_type == "gift":
            metadata.update(
                {
                    "gift_name": gift_name or "Mock Rose",
                    "repeat_count": repeat_count,
                    "diamond_count": diamond_count,
                }
            )
        event = TikTokEvent(
            event_type=event_type,
            event_id=f"mock-{uuid4()}",
            timestamp=datetime.now(timezone.utc),
            user=EventUser(display_name=display_name, user_id=user_id or f"mock:{display_name}"),
            message=message if event_type == "chat_message" else None,
            metadata=metadata,
        )
        await self.handle_event(event, allow_simulated=True)
        return event

    def _provider_request(self, kind: str) -> ProviderRequest:
        if kind == "cloud":
            secret = self.settings.cloud_api_key
            return ProviderRequest(
                base_url=self.settings.cloud_base_url,
                api_key=secret.get_secret_value() if secret else None,
                model=self.settings.cloud_model,
                temperature=self.settings.temperature,
                context_length=self.settings.context_length,
                max_output_tokens=self.settings.max_output_tokens,
                stream=self.settings.stream,
                reasoning=self.settings.reasoning,
                timeout=self.settings.timeout,
                system_prompt=self.settings.system_prompt,
                http_referer=self.settings.openrouter_http_referer,
                x_title=self.settings.openrouter_title,
            )
        secret = self.settings.llm_api_key
        return ProviderRequest(
            base_url=self.settings.llm_base_url,
            api_key=secret.get_secret_value() if secret else None,
            model=self.settings.model,
            temperature=self.settings.temperature,
            context_length=self.settings.context_length,
            max_output_tokens=self.settings.max_output_tokens,
            stream=self.settings.stream,
            reasoning=self.settings.reasoning,
            timeout=self.settings.timeout,
            system_prompt=self.settings.system_prompt,
        )

    def _provider(self, kind: str) -> LLMProvider:
        request = self._provider_request(kind)
        if self.provider_factory is not None:
            return self.provider_factory(request)
        if kind == "local":
            return LMStudioProvider(request)
        return OpenAICompatibleProvider(request)

    def _search_client(self) -> BraveSearchClient:
        secret = self.settings.brave_api_key
        api_key = secret.get_secret_value() if secret else ""
        if self.search_factory is not None:
            return self.search_factory(api_key, self.settings.search_timeout)
        return BraveSearchClient(api_key, timeout=self.settings.search_timeout)

    async def search(
        self,
        query: str,
        *,
        kind: SearchKind = "web",
    ) -> list[SearchResult]:
        if not self.settings.internet_enabled:
            raise SearchError("Internetsuche ist deaktiviert")
        if kind == "youtube" and not self.settings.youtube_enabled:
            raise SearchError("YouTube-Suche ist deaktiviert")
        if self.settings.brave_api_key is None:
            raise SearchError("Brave API Key ist nicht konfiguriert")
        try:
            results = await self._search_client().search(
                query,
                kind=kind,
                count=self.settings.search_result_limit,
            )
        except SearchError as exc:
            self.internet_connected = False
            self.last_search_error = str(exc)
            self._publish_status()
            raise
        self.internet_connected = True
        self.last_search_error = None
        self._publish_status()
        return results

    @property
    def spotify_redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.settings.port}/api/spotify/callback"

    def _spotify_client(self) -> SpotifyConnectClient:
        refresh = self.settings.spotify_refresh_token
        refresh_value = refresh.get_secret_value() if refresh is not None else None
        config = (self.settings.spotify_client_id, refresh_value)
        if self._spotify_client_instance is None or self._spotify_client_config != config:
            if self.spotify_factory is not None:
                self._spotify_client_instance = self.spotify_factory(
                    self.settings.spotify_client_id, refresh_value, 10.0
                )
            else:
                self._spotify_client_instance = SpotifyConnectClient(
                    self.settings.spotify_client_id, refresh_value, timeout=10.0
                )
            self._spotify_client_config = config
        return self._spotify_client_instance

    def spotify_authorization_url(self) -> str:
        if not self.settings.spotify_enabled or not self.settings.spotify_client_id:
            raise SpotifyError("Spotify ist nicht aktiviert oder die Client-ID fehlt")
        request = create_oauth_request(
            self.settings.spotify_client_id, self.spotify_redirect_uri
        )
        self._spotify_oauth.clear()
        self._spotify_oauth[request.state] = (request.verifier, time.monotonic())
        return request.url

    async def complete_spotify_authorization(self, code: str, state: str) -> None:
        pending = self._spotify_oauth.pop(state, None)
        if pending is None or time.monotonic() - pending[1] > 600:
            raise SpotifyError("Spotify-Anmeldung ist abgelaufen oder ungültig")
        client = SpotifyConnectClient(
            self.settings.spotify_client_id, None, timeout=10.0
        )
        refresh_token = await client.exchange_code(
            code, pending[0], self.spotify_redirect_uri
        )
        merged = self.settings.model_dump()
        merged["spotify_refresh_token"] = refresh_token
        updated = BridgeSettings.model_validate(merged)
        if self.settings_store is not None:
            self.settings_store.save(updated)
        self.settings = updated
        self._spotify_client_instance = client
        self._spotify_client_config = (self.settings.spotify_client_id, refresh_token)
        self.spotify_connected = True
        self.last_error = None
        self._publish_status()

    async def spotify_status(self) -> dict[str, object]:
        base: dict[str, object] = {
            "enabled": self.settings.spotify_enabled,
            "configured": bool(self.settings.spotify_client_id),
            "connected": False,
            "redirect_uri": self.spotify_redirect_uri,
        }
        if not self.settings.spotify_enabled or not self.settings.spotify_refresh_token:
            self.spotify_connected = False
            return base
        try:
            client = self._spotify_client()
            playback = await client.status()
            self._persist_spotify_refresh(client)
        except SpotifyError as exc:
            self.spotify_connected = False
            return {**base, "error": str(exc)}
        self.spotify_connected = True
        self.spotify_playback = playback
        return {**base, **playback, "connected": True}

    async def spotify_control(
        self, action: SpotifyControl, *, query: str | None = None
    ) -> dict[str, object]:
        if not self.settings.spotify_enabled or not self.settings.spotify_refresh_token:
            raise SpotifyError("Spotify ist nicht verbunden")
        client = self._spotify_client()
        playback = await client.control(action, query=query)
        self._persist_spotify_refresh(client)
        self.spotify_connected = True
        self.spotify_playback = playback
        self.last_error = None
        self.bus.publish({"type": "spotify", "spotify": playback})
        self._publish_status()
        return playback

    def _persist_spotify_refresh(self, client: SpotifyConnectClient) -> None:
        current = self.settings.spotify_refresh_token
        current_value = current.get_secret_value() if current is not None else None
        refreshed = getattr(client, "refresh_token", None)
        if not refreshed or refreshed == current_value:
            return
        merged = self.settings.model_dump()
        merged["spotify_refresh_token"] = refreshed
        updated = BridgeSettings.model_validate(merged)
        if self.settings_store is not None:
            self.settings_store.save(updated)
        self.settings = updated
        self._spotify_client_config = (
            self.settings.spotify_client_id,
            refreshed,
        )

    async def disconnect_spotify(self) -> None:
        merged = self.settings.model_dump()
        merged["spotify_refresh_token"] = None
        updated = BridgeSettings.model_validate(merged)
        if self.settings_store is not None:
            self.settings_store.save(updated)
        self.settings = updated
        self._spotify_client_instance = None
        self._spotify_client_config = None
        self.spotify_connected = False
        self.spotify_playback = {}
        self._publish_status()

    def _schedule_spotify(
        self, action: SpotifyControl | str, *, query: str | None = None
    ) -> None:
        task = asyncio.create_task(
            self._run_spotify(action, query=query), name=f"spotify-{action}"
        )
        self._media_tasks.add(task)
        task.add_done_callback(self._media_tasks.discard)

    async def _run_spotify(
        self, action: SpotifyControl | str, *, query: str | None = None
    ) -> None:
        try:
            await self.spotify_control(action, query=query)  # type: ignore[arg-type]
        except SpotifyError as exc:
            self.spotify_connected = False
            self.last_error = f"Spotify: {exc}"
            self._publish_status()

    async def _processor(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            if self.paused:
                continue
            if self.settings.gift_grace_seconds:
                await asyncio.sleep(self.settings.gift_grace_seconds)
                if self.paused:
                    continue
            question = self.questions.pop()
            if question is None:
                if self.state in {JarvisState.LISTENING, JarvisState.PROCESSING}:
                    self.state = JarvisState.IDLE
                    self._publish_status()
                continue
            self.current_question = question
            self.current_answer = ""
            self.state = JarvisState.PROCESSING
            self.last_error = None
            self.bus.publish({"type": "queue", "queue": self.queue_payload()})
            self._publish_status()
            self._generation_task = asyncio.create_task(
                self._answer(question), name=f"answer-{question.event_id}"
            )
            try:
                await self._generation_task
            except asyncio.CancelledError:
                if self._stopping:
                    raise
                self.current_question = None
                self.current_answer = ""
                self.state = JarvisState.IDLE
                self._publish_status()
            finally:
                self._generation_task = None
            if len(self.questions) and not self.paused:
                self._wake.set()

    async def _answer(self, question: QueuedQuestion) -> None:
        started = time.perf_counter()
        provider_kinds = provider_order(self.settings.provider, self.settings.cloud_fallback)
        failure: ProviderError | None = None
        memory = await self.memory.context_for(question.user_id, question.display_name)
        stream_context = {
            "provider": self.settings.provider,
            "model": self.settings.cloud_model if self.settings.provider == "cloud" else self.settings.model,
            "current_song": str(self.spotify_playback.get("track", "")),
        }
        prompt = build_question_prompt(
            question,
            memory.turns,
            memory_summary=memory.summary,
            stream_context=stream_context,
        )
        if (
            not question.music_request
            and self.settings.internet_enabled
            and needs_internet_search(question.message)
        ):
            try:
                results = await self.search(
                    question.message,
                    kind=requested_search_kind(question.message),
                )
                prompt = build_search_context(prompt, results)
            except SearchError:
                prompt += (
                    "\n\nDie Internetsuche ist gerade nicht verfügbar. "
                    "Erfinde keine aktuellen Informationen und sage das knapp."
                )
        for kind in provider_kinds:
            try:
                provider = self._provider(kind)
                chunks: list[str] = []
                async for chunk in provider.generate(prompt):
                    chunks.append(chunk)
                    self.current_answer = validate_public_output("".join(chunks).strip())
                    self.bus.publish({"type": "answer_chunk", "text": self.current_answer})
                answer = validate_public_output("".join(chunks).strip())
                if not answer:
                    raise ProviderError("LLM returned an empty answer")
                self.last_answer = answer
                await self.memory.record_turn(
                    ConversationTurn(
                        timestamp=question.event_timestamp,
                        user_id=question.user_id,
                        display_name=question.display_name,
                        message=question.message,
                        answer=answer,
                        intent=question.intent,
                    )
                )
                self.last_latency_ms = round((time.perf_counter() - started) * 1000)
                self.llm_connected = True
                self.current_answer = answer
                self.current_question = None
                try:
                    await self.tts.speak(answer)
                except RuntimeError as exc:
                    # TTS is an optional output path. A voice-engine or bridge
                    # failure must never turn a successful LLM answer into a
                    # fatal JARVIS ERROR state.
                    self.tts_speaking = False
                    self._speaking_until = 0.0
                    self.state = JarvisState.IDLE
                    self.last_error = f"TTS: {exc}"
                    self._publish_status()
                    return
                self.tts_speaking = True
                self._speaking_until = time.monotonic() + 1.0
                self.state = JarvisState.SPEAKING
                self.last_error = None
                self._publish_status()
                return
            except asyncio.CancelledError:
                raise
            except ProviderError as exc:
                failure = exc
                self.current_answer = ""
                self.bus.publish({"type": "answer_chunk", "text": ""})
                continue
            except RuntimeError as exc:
                self.current_question = None
                self.state = JarvisState.ERROR
                self.last_error = str(exc)
                self._publish_status()
                return

        self.questions.requeue(question)
        self.paused = True
        self.current_question = None
        self.current_answer = ""
        self.state = JarvisState.ERROR
        self.last_error = str(failure or ProviderError("LLM provider failed"))
        self.bus.publish({"type": "queue", "queue": self.queue_payload()})
        self._publish_status()

    async def _monitor(self) -> None:
        while True:
            try:
                provider = self._provider(self.settings.provider)
                self.llm_connected = await provider.health()
                speaking = await self.tts.state()
                self.tts_speaking = speaking or time.monotonic() < self._speaking_until
                if (
                    self.state == JarvisState.SPEAKING
                    and not self.tts_speaking
                    and self.current_question is None
                ):
                    self.state = JarvisState.IDLE
                self._publish_status()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.llm_connected = False
            await asyncio.sleep(2.0)

    async def set_paused(self, paused: bool) -> None:
        self.paused = paused
        if not paused:
            if self.state == JarvisState.ERROR:
                self.state = JarvisState.IDLE
                self.last_error = None
            self._wake.set()
        self._publish_status()

    async def skip_current(self) -> bool:
        task = self._generation_task
        if task is None or task.done():
            return False
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return True

    async def clear_queue(self) -> int:
        count = self.questions.clear()
        task = self._generation_task
        if task is not None and not task.done():
            count += 1
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.current_question = None
        self.current_answer = ""
        self.last_answer = ""
        self.tts_speaking = False
        self._speaking_until = 0
        self.state = JarvisState.IDLE
        self.bus.publish({"type": "answer_chunk", "text": ""})
        try:
            await self.tts.stop()
        except RuntimeError as exc:
            self.last_error = str(exc)
        self.bus.publish({"type": "queue", "queue": self.queue_payload()})
        self._publish_status()
        return count

    async def clear_memory(self, scope: str, user_id: str | None = None) -> int:
        return await self.memory.clear(scope, user_id=user_id)

    async def stop_tts(self) -> None:
        await self.tts.stop()
        self.tts_speaking = False
        self._speaking_until = 0
        if self.state == JarvisState.SPEAKING:
            self.state = JarvisState.IDLE
        self._publish_status()

    async def test_llm(self) -> dict[str, object]:
        """Test the configured provider without touching the queue or TTS."""
        kind = self.settings.provider
        request = self._provider_request(kind)
        provider = self._provider(kind)
        if not await provider.health():
            self.llm_connected = False
            self._publish_status()
            raise ProviderError(
                f'Model "{request.model or "not configured"}" is not available '
                "at the configured endpoint"
            )

        started = time.perf_counter()
        chunks = [
            chunk
            async for chunk in provider.generate(
                "Antworte in genau einem kurzen Satz: Ist NOEMA bereit?"
            )
        ]
        answer = validate_public_output("".join(chunks).strip())
        if not answer:
            raise ProviderError("LLM returned an empty answer")

        latency_ms = round((time.perf_counter() - started) * 1000)
        self.llm_connected = True
        self.last_latency_ms = latency_ms
        self.last_error = None
        self._publish_status()
        return {
            "ok": True,
            "provider": kind,
            "model": request.model,
            "answer": answer,
            "latency_ms": latency_ms,
        }

    async def update_settings(self, update: SettingsUpdate) -> dict[str, object]:
        changes = update.model_dump(exclude_none=True)
        for key in ("llm_api_key", "cloud_api_key", "brave_api_key"):
            if changes.get(key) == "":
                changes.pop(key)
        old_bridge = self.settings.tiktok_bridge_url
        merged = self.settings.model_dump()
        merged.update(changes)
        updated_settings = BridgeSettings.model_validate(merged)
        if self.settings_store is not None:
            self.settings_store.save(updated_settings)
        self.settings = updated_settings
        self.memory.enabled = self.settings.memory_enabled
        self.memory.recent_turns = self.settings.memory_recent_turns
        self.memory.max_users_ram = self.settings.memory_max_users_ram
        self.memory.max_turns_per_user_disk = self.settings.memory_max_turns_per_user_disk
        self.memory.retention_days = self.settings.memory_retention_days
        self.tts = TTSClient(self.settings.tiktok_bridge_url)
        if {"internet_enabled", "brave_api_key"} & changes.keys():
            self.internet_connected = False
            self.last_search_error = None
        if {"spotify_client_id", "spotify_enabled"} & changes.keys():
            self._spotify_client_instance = None
            self._spotify_client_config = None
            self.spotify_connected = False
        if old_bridge != self.settings.tiktok_bridge_url:
            await self._restart_connector()
        self.last_error = None
        self._publish_status()
        return self.settings.public_payload()

    def queue_payload(self) -> list[dict[str, object]]:
        return [item.model_dump(mode="json") for item in self.questions.snapshot()]

    def status_payload(self) -> dict[str, object]:
        active_model = (
            self.settings.cloud_model if self.settings.provider == "cloud" else self.settings.model
        )
        return {
            "state": self.state.value,
            "bridge_connected": self.bridge_connected,
            "llm_connected": self.llm_connected,
            "provider": self.settings.provider,
            "model": active_model,
            "local_model": self.settings.model,
            "cloud_model": self.settings.cloud_model,
            "tts_speaking": self.tts_speaking,
            "queue_length": len(self.questions),
            "last_latency_ms": self.last_latency_ms,
            "last_error": self.last_error,
            "internet_enabled": self.settings.internet_enabled,
            "internet_configured": self.settings.brave_api_key is not None,
            "internet_connected": self.internet_connected,
            "youtube_enabled": self.settings.youtube_enabled,
            "interactive_music_enabled": self.settings.interactive_music_enabled,
            "music_backend": self.settings.music_backend,
            "music_request_cooldown": self.settings.music_request_cooldown,
            "spotify_enabled": self.settings.spotify_enabled,
            "spotify_configured": bool(self.settings.spotify_client_id),
            "spotify_connected": self.spotify_connected,
            "spotify_playback": self.spotify_playback,
            "last_search_error": self.last_search_error,
            "paused": self.paused,
            "current_question": (
                self.current_question.model_dump(mode="json") if self.current_question else None
            ),
            "current_answer": self.current_answer,
            "last_answer": self.last_answer,
            "memory_enabled": self.settings.memory_enabled,
            "memory_active_users": self.memory.active_users,
            "memory_persistent_users": self.memory.persistent_users,
            "memory_persistent_ok": self.memory.persistent_ok,
        }

    def snapshot(self) -> dict[str, object]:
        return {
            "type": "snapshot",
            "status": self.status_payload(),
            "events": list(self.events),
            "queue": self.queue_payload(),
        }

    def _publish_status(self) -> None:
        self.bus.publish({"type": "status", "status": self.status_payload()})
