import asyncio
from datetime import datetime, timezone

import pytest

from app.llm import LLMProvider, ProviderError
from app.models import JarvisState, QueuedQuestion
from app.resilient_service import LiveAIService, RetryingProvider
from app.service import LiveAIService as BaseLiveAIService
from app.settings import BridgeSettings


class FlakyConnectProvider(LLMProvider):
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def generate(self, question: str):
        self.calls += 1
        if self.calls <= self.failures:
            raise ProviderError("LLM request failed (ConnectError)")
        yield "wieder online"

    async def health(self) -> bool:
        return True


class MidStreamFailureProvider(LLMProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, question: str):
        self.calls += 1
        yield "teilweise"
        raise ProviderError("LLM request failed (RemoteProtocolError)")

    async def health(self) -> bool:
        return True


class AckTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def speak(self, text: str, timeout: float = 10.0) -> None:
        self.spoken.append(text)

    async def state(self) -> bool:
        return False

    async def stop(self) -> None:
        return None


@pytest.mark.asyncio
async def test_transient_connect_error_is_retried_before_fallback() -> None:
    inner = FlakyConnectProvider(failures=2)
    provider = RetryingProvider(inner, attempts=3)

    chunks = [chunk async for chunk in provider.generate("Hallo")]

    assert chunks == ["wieder online"]
    assert inner.calls == 3


@pytest.mark.asyncio
async def test_midstream_failure_is_not_retried_to_avoid_duplicate_output() -> None:
    inner = MidStreamFailureProvider()
    provider = RetryingProvider(inner, attempts=3)

    chunks: list[str] = []
    with pytest.raises(ProviderError, match="RemoteProtocolError"):
        async for chunk in provider.generate("Hallo"):
            chunks.append(chunk)

    assert chunks == ["teilweise"]
    assert inner.calls == 1


@pytest.mark.asyncio
async def test_provider_exhaustion_does_not_pause_entire_live_session(monkeypatch) -> None:
    async def simulated_base_failure(self, question: QueuedQuestion) -> None:
        self.questions.requeue(question)
        self.paused = True
        self.current_question = None
        self.current_answer = ""
        self.state = JarvisState.ERROR
        self.last_error = "provider failed"

    monkeypatch.setattr(BaseLiveAIService, "_answer", simulated_base_failure)
    service = LiveAIService(BridgeSettings(connect_on_start=False))
    question = QueuedQuestion(
        event_id="evt-failed",
        event_timestamp=datetime.now(timezone.utc),
        user_id="viewer-1",
        display_name="Viewer",
        message="Testfrage",
    )

    await service._answer(question)

    assert service.paused is False
    assert service.state == JarvisState.IDLE
    assert service.last_error == "provider failed"
    assert all(item.event_id != question.event_id for item in service.questions.snapshot())


@pytest.mark.asyncio
async def test_natural_language_music_request_never_enters_ai_queue() -> None:
    service = LiveAIService(
        BridgeSettings(
            connect_on_start=False,
            internet_enabled=True,
            youtube_enabled=True,
            interactive_music_enabled=True,
            music_request_cooldown=5,
            brave_api_key="test-token",
        )
    )
    tts = AckTTS()
    service.tts = tts
    subscriber = await service.bus.subscribe()

    await service.add_mock_event(
        "chat_message",
        "Music Fan",
        "spiele chillout musik",
        "music-user",
    )
    await asyncio.sleep(0)

    messages: list[dict[str, object]] = []
    while not subscriber.empty():
        messages.append(subscriber.get_nowait())

    assert any(message["type"] == "music_request" for message in messages)
    assert len(service.questions) == 0
    assert service.current_question is None
    assert service.paused is False
    assert service.state == JarvisState.IDLE
    assert tts.spoken == ["Alles klar, der Musikwunsch ist angekommen."]


@pytest.mark.asyncio
async def test_media_request_is_never_woken_into_processor_even_when_service_is_running() -> None:
    service = LiveAIService(
        BridgeSettings(
            connect_on_start=False,
            internet_enabled=True,
            youtube_enabled=True,
            interactive_music_enabled=True,
            music_request_cooldown=5,
            brave_api_key="test-token",
        )
    )
    service.tts = AckTTS()
    await service.start()
    try:
        await service.add_mock_event(
            "chat_message",
            "Music Fan",
            "spiele musik youtube chillout",
            "music-user",
        )
        await asyncio.sleep(0.05)
        assert len(service.questions) == 0
        assert service.current_question is None
        assert service.paused is False
        assert service.state == JarvisState.IDLE
    finally:
        await service.stop()
