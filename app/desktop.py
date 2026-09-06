from __future__ import annotations

import threading
import time
import urllib.error
import urllib.request
import webbrowser

import uvicorn

from app.main import create_app
from app.settings import BridgeSettings
from app.settings_store import RuntimeSettingsStore


def dashboard_url(settings: BridgeSettings) -> str:
    host = "127.0.0.1" if settings.host in {"0.0.0.0", "::"} else settings.host
    return f"http://{host}:{settings.port}"


def open_dashboard_when_ready(url: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url, new=1)
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)


def main() -> None:
    store = RuntimeSettingsStore()
    settings = store.load(BridgeSettings.from_environment())
    url = dashboard_url(settings)
    threading.Thread(
        target=open_dashboard_when_ready,
        args=(url,),
        name="dashboard-opener",
        daemon=True,
    ).start()
    uvicorn.run(
        create_app(settings, settings_store=store),
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
