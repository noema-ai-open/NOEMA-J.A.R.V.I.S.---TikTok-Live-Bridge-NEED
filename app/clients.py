from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import httpx
import websockets

from app.models import TikTokEvent


EventCallback = Callable[[TikTokEvent], Awaitable[None]]
ConnectionCallback = Callable[[bool, str | None], Awaitable[None]]


def reconnect_delay(attempt: int, initial: float = 1.0, maximum: float = 30.0) -> float:
    if attempt < 0 or initial <= 0 or maximum <= 0:
        raise ValueError("invalid reconnect parameters")
    return min(maximum, initial * (2**attempt))


class TikTokBridgeClient:
    def __init__(
        self,
        websocket_url: str,
        on_event: EventCallback,
        on_connection: ConnectionCallback,
        *,
        initial_delay: float = 1.0,
        maximum_delay: float = 30.0,
    ) -> None:
        self.websocket_url = websocket_url
        self.on_event = on_event
        self.on_connection = on_connection
        self.initial_delay = initial_delay
        self.maximum_delay = maximum_delay
        self._stopping = False

    async def run(self) -> None:
        attempt = 0
        while not self._stopping:
            try:
                async with websockets.connect(
                    self.websocket_url, open_timeout=5, ping_interval=20, ping_timeout=20
                ) as socket:
                    attempt = 0
                    await self.on_connection(True, None)
                    async for raw in socket:
                        try:
                            payload = json.loads(raw)
                            event = TikTokEvent.from_websocket_payload(payload)
                            if event is not None:
                                await self.on_event(event)
                        except (ValueError, TypeError, json.JSONDecodeError):
                            continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self.on_connection(False, f"TikTok Bridge unavailable ({type(exc).__name__})")
            if self._stopping:
                break
            delay = reconnect_delay(attempt, self.initial_delay, self.maximum_delay)
            attempt += 1
            await asyncio.sleep(delay)

    async def stop(self) -> None:
        self._stopping = True


class TTSClient:
    def __init__(self, bridge_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.bridge_url = bridge_url.rstrip("/")
        self._client = client

    async def speak(self, text: str, timeout: float = 10.0) -> None:
        cleaned = " ".join(text.split()).strip()
        if not cleaned:
            raise ValueError("TTS text must not be empty")
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            response = await client.post(
                f"{self.bridge_url}/tts/test", json={"text": cleaned}, timeout=timeout
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"TTS request failed ({type(exc).__name__})") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def state(self) -> bool:
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            response = await client.get(f"{self.bridge_url}/tts/state", timeout=3.0)
            response.raise_for_status()
            return bool(response.json().get("speaking", False))
        except (httpx.HTTPError, ValueError, TypeError):
            return False
        finally:
            if owns_client:
                await client.aclose()

    async def stop(self) -> None:
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            response = await client.post(f"{self.bridge_url}/tts/stop", timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"TTS stop failed ({type(exc).__name__})") from exc
        finally:
            if owns_client:
                await client.aclose()

