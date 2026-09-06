import asyncio
import json

import httpx
import pytest

from app.clients import TTSClient, reconnect_delay


def test_reconnect_backoff_is_exponential_and_capped() -> None:
    assert [reconnect_delay(i, 1, 5) for i in range(5)] == [1, 2, 4, 5, 5]
    with pytest.raises(ValueError):
        reconnect_delay(-1)


def test_tts_client_sends_only_finished_text_and_reads_state() -> None:
    requests: list[tuple[str, str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        requests.append((request.method, request.url.path, payload))
        if request.url.path == "/tts/state":
            return httpx.Response(200, json={"speaking": True})
        return httpx.Response(202, json={"queued": True})

    async def exercise() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        tts = TTSClient("http://bridge.test", client)
        await tts.speak("  Fertige   Antwort.  ")
        assert await tts.state() is True
        await tts.stop()
        await client.aclose()

    asyncio.run(exercise())

    assert requests == [
        ("POST", "/tts/test", {"text": "Fertige Antwort."}),
        ("GET", "/tts/state", None),
        ("POST", "/tts/stop", None),
    ]
