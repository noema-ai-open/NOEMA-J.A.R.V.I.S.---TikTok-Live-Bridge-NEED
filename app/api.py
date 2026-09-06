import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.llm import ProviderError
from app.search import SearchError
from app.service import LiveAIService
from app.settings import SettingsUpdate
from app.spotify import SpotifyError


router = APIRouter()


def service(request: Request) -> LiveAIService:
    return request.app.state.service


class PauseRequest(BaseModel):
    paused: bool


class MemoryClearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["active", "user", "all"]
    user_id: str | None = Field(default=None, max_length=200)


class MockEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: Literal["chat_message", "gift", "follow", "share", "status"] = "chat_message"
    display_name: str = Field(default="Demo Viewer", min_length=1, max_length=200)
    user_id: str | None = Field(default=None, max_length=200)
    message: str | None = Field(default="Wie heißt das Spiel?", max_length=10000)
    gift_name: str | None = Field(default=None, max_length=200)
    repeat_count: int = Field(default=1, ge=1, le=10000)
    diamond_count: int = Field(default=1, ge=0, le=1000000)


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=400)
    kind: Literal["web", "youtube"] = "web"


class SpotifyControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "play", "play_album", "pause", "resume", "skip", "volume_up", "volume_down"
    ]
    query: str | None = Field(default=None, max_length=200)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/status")
async def status(request: Request) -> dict[str, object]:
    return service(request).status_payload()


@router.get("/api/events")
async def events(request: Request) -> list[dict[str, object]]:
    return list(service(request).events)


@router.get("/api/queue")
async def queue(request: Request) -> list[dict[str, object]]:
    return service(request).queue_payload()


@router.get("/api/settings")
async def get_settings(request: Request) -> dict[str, object]:
    return service(request).settings.public_payload()


@router.post("/api/settings")
async def update_settings(request: Request, body: SettingsUpdate) -> dict[str, object]:
    try:
        return await service(request).update_settings(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/diagnostics/llm")
async def test_llm(request: Request) -> dict[str, object]:
    try:
        return await service(request).test_llm()
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/api/search")
async def search(request: Request, body: SearchRequest) -> dict[str, object]:
    try:
        results = await service(request).search(body.query, kind=body.kind)
    except SearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "kind": body.kind,
        "results": [result.payload() for result in results],
    }


@router.get("/api/spotify/login")
async def spotify_login(request: Request) -> RedirectResponse:
    try:
        url = service(request).spotify_authorization_url()
    except SpotifyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse(url)


@router.get("/api/spotify/callback")
async def spotify_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        return RedirectResponse(f"/?spotify=error")
    if not code or not state:
        raise HTTPException(status_code=422, detail="Spotify callback is incomplete")
    try:
        await service(request).complete_spotify_authorization(code, state)
    except SpotifyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RedirectResponse("/?spotify=connected")


@router.get("/api/spotify/status")
async def spotify_status(request: Request) -> dict[str, object]:
    return await service(request).spotify_status()


@router.post("/api/spotify/control")
async def spotify_control(
    request: Request, body: SpotifyControlRequest
) -> dict[str, object]:
    if body.action == "play" and not body.query:
        body.query = None
    try:
        return await service(request).spotify_control(body.action, query=body.query)
    except SpotifyError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/api/spotify/disconnect")
async def spotify_disconnect(request: Request) -> dict[str, bool]:
    await service(request).disconnect_spotify()
    return {"connected": False}


@router.post("/api/control/pause")
async def pause(request: Request, body: PauseRequest) -> dict[str, bool]:
    await service(request).set_paused(body.paused)
    return {"paused": body.paused}


@router.post("/api/control/skip")
async def skip(request: Request) -> dict[str, bool]:
    return {"skipped": await service(request).skip_current()}


@router.post("/api/control/clear")
async def clear(request: Request) -> dict[str, int]:
    return {"cleared": await service(request).clear_queue()}


@router.post("/api/control/memory-clear")
async def memory_clear(request: Request, body: MemoryClearRequest) -> dict[str, int]:
    try:
        cleared = await service(request).clear_memory(body.scope, body.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"cleared": cleared}


@router.post("/api/control/tts-stop")
async def tts_stop(request: Request) -> dict[str, bool]:
    try:
        await service(request).stop_tts()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"stopped": True}


@router.post("/api/mock/event", status_code=202)
async def mock_event(request: Request, body: MockEventRequest) -> dict[str, object]:
    if body.event_type == "chat_message" and not body.message:
        raise HTTPException(status_code=422, detail="chat_message requires message")
    event = await service(request).add_mock_event(
        body.event_type,
        body.display_name,
        body.message,
        body.user_id,
        body.gift_name,
        body.repeat_count,
        body.diamond_count,
    )
    return event.model_dump(mode="json")


@router.websocket("/ws/dashboard")
async def dashboard(websocket: WebSocket) -> None:
    current: LiveAIService = websocket.app.state.service
    queue = await current.bus.subscribe()
    await websocket.accept()
    await websocket.send_json(current.snapshot())
    try:
        while True:
            message_task = asyncio.create_task(queue.get())
            client_task = asyncio.create_task(websocket.receive())
            done, pending = await asyncio.wait(
                {message_task, client_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if client_task in done and client_task.result()["type"] == "websocket.disconnect":
                break
            if message_task in done:
                await websocket.send_json(message_task.result())
    except WebSocketDisconnect:
        pass
    finally:
        current.bus.unsubscribe(queue)
