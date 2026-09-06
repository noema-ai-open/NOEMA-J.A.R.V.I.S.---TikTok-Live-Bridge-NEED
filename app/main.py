from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import router
from app.service import LiveAIService
from app.settings import BridgeSettings
from app.settings_store import RuntimeSettingsStore


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


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
    async def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

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
