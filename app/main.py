from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import router
from app.guarded_service import LiveAIService
from app.settings import BridgeSettings
from app.settings_store import RuntimeSettingsStore


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_CHAT_MUSIC_GUARD = '<script src="/static/chat-music-guard.js"></script>'
_MUSIC_CONTINUITY_GUARD = '<script src="/static/music-continuity-guard.js"></script>'
_SHOW_MODE_LAYOUT = '<link rel="stylesheet" href="/static/show-mode-layout.css">'


def create_app(
    settings: BridgeSettings | None = None,
    settings_store: RuntimeSettingsStore | None = None,
) -> FastAPI:
    store = settings_store
    if settings is None:
        store = store or RuntimeSettingsStore()
        resolved = store.load(BridgeSettings.from_environment())
    else:
        resolved = settings

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        service = LiveAIService(resolved, settings_store=store)
        app.state.service = service
        await service.start()
        try:
            yield
        finally:
            await service.stop()

    app = FastAPI(title="NOEMA J.A.R.V.I.S. Live AI Bridge", version=__version__, lifespan=lifespan)

    @app.middleware("http")
    async def identify_embedded_media_client(request: Request, call_next):
        response = await call_next(request)
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    app.include_router(router)

    @app.get("/", include_in_schema=False)
    async def index() -> HTMLResponse:
        html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        if _SHOW_MODE_LAYOUT not in html:
            html = html.replace("</head>", f"{_SHOW_MODE_LAYOUT}</head>")
        guards = "".join((_CHAT_MUSIC_GUARD, _MUSIC_CONTINUITY_GUARD))
        if _CHAT_MUSIC_GUARD not in html or _MUSIC_CONTINUITY_GUARD not in html:
            html = html.replace("</body>", f"{guards}</body>")
        return HTMLResponse(html)

    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
    return app


app = create_app()


def main() -> None:
    store = RuntimeSettingsStore()
    settings = store.load(BridgeSettings.from_environment())
    uvicorn.run(
        create_app(settings, settings_store=store),
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
