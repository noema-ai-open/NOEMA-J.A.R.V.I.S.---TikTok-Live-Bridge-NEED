import asyncio
import json

import httpx
import pytest

from app.llm import (
    ConversationTurn,
    LMStudioProvider,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderRequest,
    ProviderTimeout,
    SYSTEM_PROMPT,
    build_question_prompt,
)
from app.models import GiftInfo, QueuedQuestion


def provider_config(**overrides) -> ProviderRequest:
    values = {
        "base_url": "http://lm.test/v1",
        "api_key": "test-secret",
        "model": "configured-model",
        "temperature": 0.6,
        "context_length": 8192,
        "max_output_tokens": 120,
        "stream": True,
        "reasoning": False,
        "timeout": 2.0,
    }
    values.update(overrides)
    return ProviderRequest(**values)


def test_system_prompt_is_spoken_live_safe_and_avoids_invented_context() -> None:
    assert "lokale KI-Co-Host von NOEMA AI" in SYSTEM_PROMPT
    assert "höchstens zehn kurzen Sätzen" in SYSTEM_PROMPT
    assert "freiwillige Geschenke" in SYSTEM_PROMPT
    assert "setze niemanden unter Druck" in SYSTEM_PROMPT
    assert "kurze passende Rückfrage" in SYSTEM_PROMPT
    assert "nicht künstlich überdreht" in SYSTEM_PROMPT
    assert "Wenn Kontext fehlt" in SYSTEM_PROMPT
    assert "keine rassistischen" in SYSTEM_PROMPT
    assert "sexuell expliziten Inhalte" in SYSTEM_PROMPT
    assert "Bleiben wir respektvoll" in SYSTEM_PROMPT
    assert "kein Reasoning" in SYSTEM_PROMPT
    assert "ausdrücklich darum bittet, einen Text vorzulesen" in SYSTEM_PROMPT


def test_read_aloud_request_gets_long_form_output_contract() -> None:
    question = QueuedQuestion(
        event_id="read-1",
        event_timestamp=1.0,
        user_id="u1",
        display_name="Sandra",
        message="Lies bitte Psalm 91 vor",
        sequence=1,
    )

    prompt = build_question_prompt(question)

    assert "Vorlesewunsch darf die Antwort länger sein" in prompt
    assert "Lies direkt vor, ohne Einleitung oder Ablenkung" in prompt


def test_openai_compatible_streaming_request() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["json"] = json.loads(request.content)
        body = (
            'data: {"choices":[{"delta":{"content":"Hallo "}}]}\n\n'
            'data: {"choices":[{"delta":{"reasoning":"hidden","content":"Welt"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async def exercise() -> list[str]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleProvider(provider_config(), client)
        chunks = [chunk async for chunk in provider.generate("Eine kurze Frage")]
        await client.aclose()
        return chunks

    chunks = asyncio.run(exercise())
    assert chunks == ["Hallo ", "Welt"]
    assert seen["url"] == "http://lm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer test-secret"
    assert seen["json"]["model"] == "configured-model"
    assert seen["json"]["max_tokens"] == 120
    assert seen["json"]["stream"] is True
    assert seen["json"]["messages"][0]["content"] == SYSTEM_PROMPT
    assert "reasoning" not in seen["json"]


def test_openrouter_request_disables_reasoning_without_exposing_it() -> None:
    provider = OpenAICompatibleProvider(
        provider_config(base_url="https://openrouter.ai/api/v1", reasoning=False)
    )

    payload = provider._payload("Antworte kurz")

    assert payload["reasoning"] == {"effort": "none", "exclude": True}


def test_lm_studio_native_stream_forces_reasoning_off_and_only_yields_messages() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = json.loads(request.content)
        body = (
            'event: reasoning.delta\n'
            'data: {"type":"reasoning.delta","content":"hidden"}\n\n'
            'event: message.delta\n'
            'data: {"type":"message.delta","content":"NOEMA "}\n\n'
            'event: message.delta\n'
            'data: {"type":"message.delta","content":"ist bereit."}\n\n'
            'event: chat.end\n'
            'data: {"type":"chat.end","result":{"output":[]}}\n\n'
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async def exercise() -> list[str]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = LMStudioProvider(provider_config(), client)
        chunks = [chunk async for chunk in provider.generate("Kurzer Test")]
        await client.aclose()
        return chunks

    assert asyncio.run(exercise()) == ["NOEMA ", "ist bereit."]
    assert seen["url"] == "http://lm.test/api/v1/chat"
    assert seen["json"]["reasoning"] == "off"
    assert "integrations" not in seen["json"]
    assert seen["json"]["store"] is False
    assert seen["json"]["context_length"] == 8192


def test_custom_system_prompt_is_sent_to_lm_studio() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            text='event: message.delta\ndata: {"type":"message.delta","content":"Bereit."}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    async def exercise() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = LMStudioProvider(provider_config(system_prompt="Mein Live-Prompt"), client)
        _ = [chunk async for chunk in provider.generate("Test")]
        await client.aclose()

    asyncio.run(exercise())
    assert seen["json"]["system_prompt"] == "Mein Live-Prompt"


def test_lm_studio_native_non_streaming_ignores_reasoning_output() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "output": [
                    {"type": "reasoning", "content": "hidden"},
                    {"type": "message", "content": "Nur sichtbarer Text."},
                ]
            },
        )

    async def exercise() -> list[str]:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = LMStudioProvider(provider_config(stream=False), client)
        chunks = [chunk async for chunk in provider.generate("Kurzer Test")]
        await client.aclose()
        return chunks

    assert asyncio.run(exercise()) == ["Nur sichtbarer Text."]


def test_provider_timeout_is_translated() -> None:
    def timeout(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    async def exercise() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
        provider = OpenAICompatibleProvider(provider_config(), client)
        with pytest.raises(ProviderTimeout, match="timed out"):
            _ = [chunk async for chunk in provider.generate("Frage")]
        await client.aclose()

    asyncio.run(exercise())


def test_provider_rejects_reserved_model_tokens() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        body = (
            'data: {"choices":[{"delta":{"content":"Hallo"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"<unused24>"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    async def exercise() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleProvider(provider_config(), client)
        with pytest.raises(ProviderError, match="reserved or internal"):
            _ = [chunk async for chunk in provider.generate("Frage")]
        await client.aclose()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("configured_model", "advertised_models", "expected"),
    [
        ("configured-model", ["configured-model", "another-model"], True),
        ("configured-model", ["another-model"], False),
        ("", ["configured-model"], False),
    ],
)
def test_provider_health_requires_exact_configured_model(
    configured_model: str, advertised_models: list[str], expected: bool
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://lm.test/v1/models"
        return httpx.Response(200, json={"data": [{"id": model} for model in advertised_models]})

    async def exercise() -> bool:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleProvider(provider_config(model=configured_model), client)
        result = await provider.health()
        await client.aclose()
        return result

    assert asyncio.run(exercise()) is expected


def test_gift_prompts_distinguish_supporter_and_spotlight(event_factory) -> None:
    rose_event = event_factory(
        event_type="gift", message=None, metadata={"gift_name": "Rose"}
    )
    donut_event = event_factory(
        event_type="gift", message=None, metadata={"gift_name": "Donut"}
    )
    question = QueuedQuestion(
        event_id="question-1",
        event_timestamp=rose_event.timestamp,
        user_id="fan",
        display_name="Alex",
        message="Was spielst du?",
    )

    question.gift = GiftInfo.from_event(rose_event)
    supporter_prompt = build_question_prompt(question)
    question.gift = GiftInfo.from_event(donut_event)
    spotlight_prompt = build_question_prompt(question)

    assert "sehr kurzen natürlichen Halbsatz" in supporter_prompt
    assert "Rose" in supporter_prompt
    assert "SPOTLIGHT" in spotlight_prompt
    assert "persönlich" in spotlight_prompt
    assert "Donut" in spotlight_prompt
    assert "Alex" in spotlight_prompt


def test_normal_chat_prompt_requests_a_short_reaction(event_factory) -> None:
    event = event_factory(message="Tolles Design")
    chat = QueuedQuestion(
        event_id=event.event_id,
        event_timestamp=event.timestamp,
        user_id=event.user.user_id,
        display_name=event.user.display_name,
        message=event.message or "",
        is_question=False,
        priority_reason="chat",
    )

    prompt = build_question_prompt(chat)

    assert "schreibt im TikTok-Live" in prompt
    assert "Reagiere direkt, freundlich und sehr kurz" in prompt


def test_question_prompt_includes_conversation_context(event_factory) -> None:
    event = event_factory(message="Und welches davon ist dein Favorit?")
    question = QueuedQuestion(
        event_id=event.event_id,
        event_timestamp=event.timestamp,
        user_id=event.user.user_id,
        display_name=event.user.display_name,
        message=event.message or "",
    )
    history = [
        ConversationTurn("Alex", "Nenne zwei Synthwave-Alben", "OutRun und Atlas."),
    ]

    prompt = build_question_prompt(question, history)

    assert "Bisheriger Live-Dialog" in prompt
    assert "Zuschauer Alex: Nenne zwei Synthwave-Alben" in prompt
    assert "J.A.R.V.I.S.: OutRun und Atlas." in prompt
    assert "Aktuelle Nachricht:" in prompt
    assert "ein bis drei kurzen Sätzen" in prompt
