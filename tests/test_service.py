import asyncio

from app.llm import (
    ConversationTurn,
    LMStudioProvider,
    LLMProvider,
    OpenAICompatibleProvider,
    ProviderTimeout,
)
from app.search import SearchResult
from app.service import LiveAIService
from app.settings import BridgeSettings


class FakeProvider(LLMProvider):
    async def generate(self, question: str):
        assert "Wie heißt das Spiel?" in question
        yield "Das ist "
        yield "ein Testspiel."

    async def health(self) -> bool:
        return True


class FakeTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.stop_calls = 0

    async def speak(self, text: str, timeout: float = 10.0) -> None:
        self.spoken.append(text)

    async def state(self) -> bool:
        return False

    async def stop(self) -> None:
        self.stop_calls += 1


class BlockingProvider(LLMProvider):
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def generate(self, question: str):
        self.started.set()
        await asyncio.Event().wait()
        yield "unreachable"

    async def health(self) -> bool:
        return True


class FailingProvider(LLMProvider):
    async def generate(self, question: str):
        if False:
            yield ""
        raise ProviderTimeout("LLM request timed out")

    async def health(self) -> bool:
        return False


class ReservedTokenProvider(LLMProvider):
    async def generate(self, question: str):
        yield "Beginn"
        yield "<unused24>"

    async def health(self) -> bool:
        return True


class DiagnosticProvider(LLMProvider):
    async def generate(self, question: str):
        assert "Ist NOEMA bereit?" in question
        yield "NOEMA ist bereit."

    async def health(self) -> bool:
        return True


class CapturingGiftProvider(LLMProvider):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, question: str):
        self.prompts.append(question)
        yield "Alex, danke für den Donut. Das ist ein Testspiel."

    async def health(self) -> bool:
        return True


class CapturingChatProvider(LLMProvider):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, prompt: str):
        self.prompts.append(prompt)
        yield "Danke, das freut mich!"

    async def health(self) -> bool:
        return True


class CapturingInternetProvider(LLMProvider):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(self, prompt: str):
        self.prompts.append(prompt)
        yield "In Berlin sind es aktuell 20 Grad."

    async def health(self) -> bool:
        return True


class FakeSearchClient:
    def __init__(self) -> None:
        self.queries: list[tuple[str, str, int]] = []

    async def search(self, query: str, *, kind: str = "web", count: int = 4):
        self.queries.append((query, kind, count))
        return [
            SearchResult(
                "Wetter Berlin",
                "https://example.test/weather",
                "Aktuell 20 Grad und trocken.",
            )
        ]


def test_default_provider_selection_separates_local_and_cloud() -> None:
    service = LiveAIService(
        BridgeSettings(
            connect_on_start=False,
            model="local-model",
            cloud_model="cloud-model",
        )
    )

    assert isinstance(service._provider("local"), LMStudioProvider)
    assert isinstance(service._provider("cloud"), OpenAICompatibleProvider)


def test_question_to_streamed_answer_and_tts_pipeline() -> None:
    async def exercise() -> tuple[LiveAIService, FakeTTS]:
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False, model="mock-model", gift_grace_seconds=0
            ),
            provider_factory=lambda config: FakeProvider(),
        )
        tts = FakeTTS()
        service.tts = tts
        await service.start()
        try:
            await service.add_mock_event(
                "chat_message", "Demo", "Wie heißt das Spiel?", "demo-user"
            )
            for _ in range(50):
                if tts.spoken:
                    break
                await asyncio.sleep(0.01)
            return service, tts
        finally:
            await service.stop()

    service, tts = asyncio.run(exercise())
    assert tts.spoken == ["Das ist ein Testspiel."]
    assert service.last_answer == "Das ist ein Testspiel."
    assert service.last_latency_ms is not None
    assert len(service.questions) == 0


def test_normal_chat_message_gets_a_short_llm_and_tts_reaction() -> None:
    async def exercise() -> tuple[CapturingChatProvider, FakeTTS]:
        provider = CapturingChatProvider()
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False, model="chat-model", gift_grace_seconds=0
            ),
            provider_factory=lambda config: provider,
        )
        tts = FakeTTS()
        service.tts = tts
        await service.start()
        try:
            await service.add_mock_event(
                "chat_message", "Demo", "Tolles Design", "chat-user"
            )
            for _ in range(50):
                if tts.spoken:
                    break
                await asyncio.sleep(0.01)
            return provider, tts
        finally:
            await service.stop()

    provider, tts = asyncio.run(exercise())

    assert "schreibt im TikTok-Live" in provider.prompts[0]
    assert tts.spoken == ["Danke, das freut mich!"]


def test_external_simulated_events_are_ignored(event_factory) -> None:
    async def exercise() -> LiveAIService:
        service = LiveAIService(BridgeSettings(connect_on_start=False))
        event = event_factory(
            message="Hello!",
            display_name="Viewer 9348",
            metadata={"simulated": True},
        )
        await service.handle_event(event)
        return service

    service = asyncio.run(exercise())
    assert list(service.events) == []
    assert len(service.questions) == 0


def test_clear_queue_cancels_active_generation_and_stops_tts() -> None:
    async def exercise() -> tuple[int, LiveAIService, FakeTTS]:
        provider = BlockingProvider()
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False,
                model="blocking-model",
                gift_grace_seconds=0,
            ),
            provider_factory=lambda config: provider,
        )
        tts = FakeTTS()
        service.tts = tts
        await service.start()
        try:
            await service.add_mock_event("chat_message", "One", "Hallo", "one")
            await provider.started.wait()
            await service.add_mock_event("chat_message", "Two", "Hallo", "two")
            cleared = await service.clear_queue()
            return cleared, service, tts
        finally:
            await service.stop()

    cleared, service, tts = asyncio.run(exercise())
    assert cleared == 2
    assert len(service.questions) == 0
    assert service.current_question is None
    assert service.current_answer == ""
    assert service.last_answer == ""
    assert service.status_payload()["state"] == "IDLE"
    assert tts.stop_calls == 1


def test_successful_answers_are_used_as_live_context() -> None:
    async def exercise() -> tuple[CapturingChatProvider, LiveAIService]:
        provider = CapturingChatProvider()
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False, model="chat-model", gift_grace_seconds=0
            ),
            provider_factory=lambda config: provider,
        )
        service.tts = FakeTTS()
        await service.start()
        try:
            await service.add_mock_event("chat_message", "Alex", "Tolles Design", "alex")
            for _ in range(50):
                if len(provider.prompts) == 1 and service.current_question is None:
                    break
                await asyncio.sleep(0.01)
            await service.add_mock_event(
                "chat_message", "Alex", "Was gefällt dir daran?", "alex"
            )
            for _ in range(50):
                if len(provider.prompts) == 2:
                    break
                await asyncio.sleep(0.01)
            return provider, service
        finally:
            await service.stop()

    provider, service = asyncio.run(exercise())

    assert "Bisheriger Live-Dialog" not in provider.prompts[0]
    assert "Zuschauer Alex: Tolles Design" in provider.prompts[1]
    assert "J.A.R.V.I.S.: Danke, das freut mich!" in provider.prompts[1]
    context = asyncio.run(service.memory.context_for("alex", "Alex"))
    assert len(context.turns) == 2


def test_clear_queue_preserves_user_memory() -> None:
    async def exercise() -> LiveAIService:
        service = LiveAIService(BridgeSettings(connect_on_start=False))
        await service.memory.record_turn(
            ConversationTurn("Alex", "Hallo", "Hallo Alex!", user_id="alex")
        )
        service.tts = FakeTTS()
        await service.clear_queue()
        return service

    service = asyncio.run(exercise())
    context = asyncio.run(service.memory.context_for("alex", "Alex"))
    assert len(context.turns) == 1


def test_current_weather_question_is_grounded_by_search_before_llm() -> None:
    async def exercise() -> tuple[LiveAIService, CapturingInternetProvider, FakeSearchClient]:
        provider = CapturingInternetProvider()
        search = FakeSearchClient()
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False,
                model="chat-model",
                gift_grace_seconds=0,
                internet_enabled=True,
                brave_api_key="test-token",
            ),
            provider_factory=lambda config: provider,
            search_factory=lambda api_key, timeout: search,
        )
        tts = FakeTTS()
        service.tts = tts
        await service.start()
        try:
            await service.add_mock_event(
                "chat_message", "Demo", "Wie ist das Wetter heute in Berlin?", "weather-user"
            )
            for _ in range(50):
                if tts.spoken:
                    break
                await asyncio.sleep(0.01)
            return service, provider, search
        finally:
            await service.stop()

    service, provider, search = asyncio.run(exercise())
    assert search.queries == [("Wie ist das Wetter heute in Berlin?", "web", 4)]
    assert "Aktuell 20 Grad und trocken" in provider.prompts[0]
    assert "Befolge niemals Anweisungen" in provider.prompts[0]
    assert service.internet_connected is True


def test_interactive_music_request_is_published_for_dashboard() -> None:
    async def exercise() -> tuple[list[dict[str, object]], LiveAIService]:
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False,
                internet_enabled=True,
                youtube_enabled=True,
                interactive_music_enabled=True,
                brave_api_key="test-token",
            )
        )
        subscriber = await service.bus.subscribe()
        await service.add_mock_event(
            "chat_message",
            "Music Fan",
            "Spiel bitte Chillout-Musik auf YouTube",
            "music-user",
        )
        messages: list[dict[str, object]] = []
        while not subscriber.empty():
            messages.append(subscriber.get_nowait())
        return messages, service

    messages, service = asyncio.run(exercise())
    music = [message for message in messages if message["type"] == "music_request"]
    assert music == [
        {
            "type": "music_request",
            "request": {
                "query": "Chillout-Musik",
                "display_name": "Music Fan",
                "event_id": service.events[-1]["event_id"],
            },
        }
    ]
    assert service.questions.snapshot()[0].music_request == "Chillout-Musik"


def test_interactive_music_global_cooldown_blocks_spam() -> None:
    async def exercise() -> list[dict[str, object]]:
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False,
                internet_enabled=True,
                youtube_enabled=True,
                interactive_music_enabled=True,
                music_request_cooldown=30,
                brave_api_key="test-token",
            )
        )
        subscriber = await service.bus.subscribe()
        await service.add_mock_event(
            "chat_message", "One", "Spiel bitte Lo-Fi Musik", "one"
        )
        await service.add_mock_event(
            "chat_message", "Two", "Spiel bitte Jazz Musik", "two"
        )
        messages: list[dict[str, object]] = []
        while not subscriber.empty():
            messages.append(subscriber.get_nowait())
        return messages

    messages = asyncio.run(exercise())
    assert len([item for item in messages if item["type"] == "music_request"]) == 1


def test_music_control_command_is_published_and_not_sent_to_llm_queue() -> None:
    async def exercise() -> tuple[list[dict[str, object]], LiveAIService]:
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False,
                youtube_enabled=True,
                interactive_music_enabled=True,
            )
        )
        subscriber = await service.bus.subscribe()
        await service.add_mock_event("chat_message", "DJ", "/pause", "music-dj")
        messages: list[dict[str, object]] = []
        while not subscriber.empty():
            messages.append(subscriber.get_nowait())
        return messages, service

    messages, service = asyncio.run(exercise())
    controls = [message for message in messages if message["type"] == "music_control"]
    assert controls == [
        {
            "type": "music_control",
            "control": {
                "action": "pause",
                "display_name": "DJ",
                "event_id": service.events[-1]["event_id"],
            },
        }
    ]
    assert len(service.questions) == 0


def test_spotify_music_control_runs_privately_and_bypasses_llm_queue() -> None:
    class FakeSpotify:
        def __init__(self) -> None:
            self.controls: list[tuple[str, str | None]] = []

        async def control(self, action: str, *, query: str | None = None):
            self.controls.append((action, query))
            return {"connected": True, "track": "Private Track", "device": "WK02"}

        async def status(self):
            return {"connected": True, "track": "Private Track", "device": "WK02"}

    async def exercise() -> tuple[LiveAIService, FakeSpotify]:
        fake = FakeSpotify()
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False,
                interactive_music_enabled=True,
                music_backend="spotify",
                spotify_enabled=True,
                spotify_client_id="client-id",
                spotify_refresh_token="refresh",
            ),
            spotify_factory=lambda client_id, refresh, timeout: fake,
        )
        await service.add_mock_event("chat_message", "DJ", "/pause", "music-dj")
        for _ in range(20):
            if fake.controls:
                break
            await asyncio.sleep(0.01)
        return service, fake

    service, fake = asyncio.run(exercise())
    assert fake.controls == [("pause", None)]
    assert len(service.questions) == 0


def test_spotify_album_command_plays_context_and_bypasses_llm_queue() -> None:
    class FakeSpotify:
        def __init__(self) -> None:
            self.controls: list[tuple[str, str | None]] = []

        async def control(self, action: str, *, query: str | None = None):
            self.controls.append((action, query))
            return {"connected": True, "track": "One More Time", "device": "WK02"}

    async def exercise() -> tuple[LiveAIService, FakeSpotify]:
        fake = FakeSpotify()
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False,
                interactive_music_enabled=True,
                music_backend="spotify",
                spotify_enabled=True,
                spotify_client_id="client-id",
                spotify_refresh_token="refresh",
            ),
            spotify_factory=lambda client_id, refresh, timeout: fake,
        )
        await service.add_mock_event(
            "chat_message", "DJ", "/album Daft Punk Discovery", "album-dj"
        )
        for _ in range(20):
            if fake.controls:
                break
            await asyncio.sleep(0.01)
        return service, fake

    service, fake = asyncio.run(exercise())
    assert fake.controls == [("play_album", "Daft Punk Discovery")]
    assert len(service.questions) == 0


def test_provider_failure_requeues_question_and_pauses_without_retry_loop() -> None:
    async def exercise() -> LiveAIService:
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False, model="offline-model", gift_grace_seconds=0
            ),
            provider_factory=lambda config: FailingProvider(),
        )
        service.tts = FakeTTS()
        await service.start()
        try:
            await service.add_mock_event(
                "chat_message", "Demo", "Warum ist das so?", "demo-user"
            )
            for _ in range(50):
                if service.paused:
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.03)
            return service
        finally:
            await service.stop()

    service = asyncio.run(exercise())
    assert service.paused is True
    assert service.status_payload()["state"] == "ERROR"
    assert service.status_payload()["queue_length"] == 1
    assert service.last_error == "LLM request timed out"


def test_cloud_failure_falls_back_to_local_without_requeue() -> None:
    calls: list[str] = []

    class Provider(LLMProvider):
        def __init__(self, model: str) -> None:
            self.model = model

        async def generate(self, prompt: str):
            calls.append(self.model)
            if self.model == "cloud-model":
                raise ProviderTimeout("cloud unavailable")
            yield "Lokaler Fallback funktioniert."

        async def health(self) -> bool:
            return True

    async def exercise() -> tuple[LiveAIService, FakeTTS]:
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False,
                provider="cloud",
                cloud_fallback=True,
                cloud_model="cloud-model",
                model="local-model",
                gift_grace_seconds=0,
            ),
            provider_factory=lambda config: Provider(config.model),
        )
        tts = FakeTTS()
        service.tts = tts
        await service.start()
        try:
            await service.add_mock_event("chat_message", "Sandra", "Wie geht es dir?", "sandra")
            for _ in range(50):
                if tts.spoken:
                    break
                await asyncio.sleep(0.01)
            return service, tts
        finally:
            await service.stop()

    service, tts = asyncio.run(exercise())
    assert calls == ["cloud-model", "local-model"]
    assert tts.spoken == ["Lokaler Fallback funktioniert."]
    assert len(service.questions) == 0
    assert service.paused is False


def test_only_current_users_memory_is_added_to_follow_up_prompt(tmp_path) -> None:
    from app.memory import MemoryManager

    async def exercise() -> str:
        provider = CapturingChatProvider()
        memory = MemoryManager(tmp_path / "memory")
        await memory.record_turn(
            ConversationTurn("Peter", "Wetter morgen in Hamburg?", "Regen.", user_id="peter")
        )
        await memory.record_turn(
            ConversationTurn("Sandra", "Wetter morgen in Chemnitz?", "Sonnig.", user_id="sandra")
        )
        await memory.flush()
        service = LiveAIService(
            BridgeSettings(connect_on_start=False, gift_grace_seconds=0),
            provider_factory=lambda config: provider,
            memory_manager=memory,
        )
        service.tts = FakeTTS()
        await service.start()
        try:
            await service.add_mock_event("chat_message", "Sandra", "Und Dienstag?", "sandra")
            for _ in range(50):
                if provider.prompts:
                    break
                await asyncio.sleep(0.01)
            return provider.prompts[0]
        finally:
            await service.stop()

    prompt = asyncio.run(exercise())
    assert "Chemnitz" in prompt
    assert "Hamburg" not in prompt


def test_reserved_tokens_never_reach_tts_and_question_is_preserved() -> None:
    async def exercise() -> tuple[LiveAIService, FakeTTS]:
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False, model="broken-model", gift_grace_seconds=0
            ),
            provider_factory=lambda config: ReservedTokenProvider(),
        )
        tts = FakeTTS()
        service.tts = tts
        await service.start()
        try:
            await service.add_mock_event(
                "chat_message", "Demo", "Was passiert hier?", "demo-user"
            )
            for _ in range(50):
                if service.paused:
                    break
                await asyncio.sleep(0.01)
            return service, tts
        finally:
            await service.stop()

    service, tts = asyncio.run(exercise())
    assert tts.spoken == []
    assert service.current_answer == ""
    assert service.status_payload()["queue_length"] == 1
    assert service.last_error == "LLM emitted reserved or internal tokens"


def test_llm_diagnostic_never_uses_tts_or_queue() -> None:
    async def exercise() -> tuple[dict[str, object], LiveAIService, FakeTTS]:
        service = LiveAIService(
            BridgeSettings(connect_on_start=False, model="diagnostic-model"),
            provider_factory=lambda config: DiagnosticProvider(),
        )
        tts = FakeTTS()
        service.tts = tts
        result = await service.test_llm()
        return result, service, tts

    result, service, tts = asyncio.run(exercise())
    assert result["ok"] is True
    assert result["model"] == "diagnostic-model"
    assert result["answer"] == "NOEMA ist bereit."
    assert isinstance(result["latency_ms"], int)
    assert tts.spoken == []
    assert len(service.questions) == 0


def test_gift_during_grace_window_changes_live_prompt_and_priority() -> None:
    async def exercise() -> tuple[CapturingGiftProvider, FakeTTS]:
        provider = CapturingGiftProvider()
        service = LiveAIService(
            BridgeSettings(
                connect_on_start=False,
                model="gift-model",
                gift_grace_seconds=0.05,
            ),
            provider_factory=lambda config: provider,
        )
        tts = FakeTTS()
        service.tts = tts
        await service.start()
        try:
            await service.add_mock_event(
                "chat_message", "Alex", "Was spielst du?", "gift-user"
            )
            await asyncio.sleep(0.01)
            await service.add_mock_event(
                "gift",
                "Alex",
                None,
                "gift-user",
                "Donut",
                1,
                30,
            )
            for _ in range(100):
                if tts.spoken:
                    break
                await asyncio.sleep(0.01)
            return provider, tts
        finally:
            await service.stop()

    provider, tts = asyncio.run(exercise())
    assert "SPOTLIGHT" in provider.prompts[0]
    assert "Donut" in provider.prompts[0]
    assert tts.spoken == ["Alex, danke für den Donut. Das ist ein Testspiel."]

def test_youtube_requests_and_search_never_contact_unavailable_spotify() -> None:
    def forbidden_spotify(*args):
        raise AssertionError("YouTube must not instantiate a Spotify client")

    async def exercise():
        for message, query in [
            ("spiele Nightcall", "Nightcall"),
            ("spiele 80er", "80er"),
            ("/musik Nightcall", "Nightcall"),
        ]:
            search = FakeSearchClient()
            service = LiveAIService(
                BridgeSettings(
                    connect_on_start=False, internet_enabled=True, youtube_enabled=True,
                    interactive_music_enabled=True, music_backend="youtube",
                    brave_api_key="test", spotify_enabled=False,
                    spotify_client_id="unavailable", spotify_refresh_token="stale-token",
                ),
                search_factory=lambda *args: search,
                spotify_factory=forbidden_spotify,
            )
            subscriber = await service.bus.subscribe()
            await service.add_mock_event("chat_message", "DJ", message, "dj")
            messages = []
            while not subscriber.empty():
                messages.append(subscriber.get_nowait())
            request = next(m["request"] for m in messages if m["type"] == "music_request")
            assert request["query"] == query
            await service.search(request["query"], kind="youtube")
            assert search.queries == [(query, "youtube", 4)]
            assert service.last_search_error is None
            assert (await service.spotify_status())["connected"] is False
    asyncio.run(exercise())
