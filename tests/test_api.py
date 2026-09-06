from fastapi.testclient import TestClient

from app.llm import LLMProvider
from app.main import create_app
from app.search import SearchResult
from app.settings import BridgeSettings
from app.settings_store import RuntimeSettingsStore


class APIDiagnosticProvider(LLMProvider):
    async def generate(self, question: str):
        yield "Diagnose erfolgreich."

    async def health(self) -> bool:
        return True


class APISearchClient:
    async def search(self, query: str, *, kind: str = "web", count: int = 4):
        assert query == "NOEMA Musik"
        assert kind == "youtube"
        assert count == 4
        return [
            SearchResult(
                "NOEMA Track",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "Test result",
                "dQw4w9WgXcQ",
            )
        ]


def test_health_and_frontend() -> None:
    app = create_app(BridgeSettings(connect_on_start=False))
    with TestClient(app) as client:
        health = client.get("/health")
        frontend = client.get("/")
        stylesheet = client.get("/static/style.css")
        reactor = client.get("/static/assets/noema-reactor.png")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert frontend.status_code == 200
    assert frontend.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert '<meta name="referrer" content="strict-origin-when-cross-origin">' in frontend.text
    assert "NOEMA J.A.R.V.I.S." in frontend.text
    assert "jarvis-core" in frontend.text
    assert "reactor-ring" in frontend.text
    assert stylesheet.status_code == 200
    assert "assets/noema-reactor.png" in stylesheet.text
    assert reactor.status_code == 200
    assert reactor.headers["content-type"] == "image/png"
    assert "diamond-count" in frontend.text
    assert "TikTok Show" in frontend.text
    assert "Demo Donut" in frontend.text
    assert "Internet &amp; Musik" in frontend.text
    assert "youtube-player" in frontend.text
    assert "music-open-youtube" in frontend.text
    assert "command-deck" in frontend.text
    assert "/musik" in frontend.text
    assert "/album" in frontend.text
    assert frontend.text.index('id="jarvis-state"') < frontend.text.index("command-deck")
    assert frontend.text.index("command-deck") < frontend.text.index('id="current-question"')
    assert "widget_referrer: location.href" in client.get("/static/app.js").text
    assert 'textarea name="system_prompt"' in frontend.text
    assert "spotify-connect" in frontend.text
    assert 'id="provider-cloud-btn"' in frontend.text
    assert 'id="provider-local-btn"' in frontend.text
    assert 'class="provider-mode"' in frontend.text
    assert 'name="provider" value="cloud" type="radio"' in frontend.text
    assert 'name="provider" value="local" type="radio"' in frontend.text


def test_spotify_login_starts_pkce_redirect_without_exposing_a_secret() -> None:
    app = create_app(
        BridgeSettings(
            connect_on_start=False,
            spotify_enabled=True,
            spotify_client_id="public-client-id",
        )
    )
    with TestClient(app) as client:
        response = client.get("/api/spotify/login", follow_redirects=False)

    assert response.status_code in {302, 307}
    assert response.headers["location"].startswith("https://accounts.spotify.com/authorize?")
    assert "client_secret" not in response.headers["location"]


def test_spotify_refresh_token_is_never_returned_by_settings_api() -> None:
    app = create_app(
        BridgeSettings(
            connect_on_start=False,
            spotify_enabled=True,
            spotify_client_id="public-client-id",
            spotify_refresh_token="private-refresh-token",
        )
    )
    with TestClient(app) as client:
        response = client.get("/api/settings")

    assert response.status_code == 200
    assert response.json()["spotify_connected"] is True
    assert "private-refresh-token" not in response.text
    assert "spotify_refresh_token" not in response.text


def test_system_prompt_can_be_updated() -> None:
    app = create_app(BridgeSettings(connect_on_start=False))
    with TestClient(app) as client:
        updated = client.post("/api/settings", json={"system_prompt": "Eigener Prompt"})
        fetched = client.get("/api/settings")

    assert updated.status_code == 200
    assert updated.json()["system_prompt"] == "Eigener Prompt"
    assert fetched.json()["system_prompt"] == "Eigener Prompt"


def test_memory_clear_endpoint_is_explicit_and_separate(tmp_path) -> None:
    from app.memory import ConversationTurn, MemoryManager

    memory = MemoryManager(tmp_path / "memory")
    app = create_app(
        BridgeSettings(connect_on_start=False),
    )
    app.state  # keep construction explicit for type checkers
    with TestClient(app) as client:
        app.state.service.memory = memory
        import asyncio

        async def seed() -> None:
            await memory.record_turn(
                ConversationTurn("Sandra", "Hallo", "Hallo!", user_id="sandra")
            )
            await memory.flush()

        asyncio.run(seed())
        response = client.post("/api/control/memory-clear", json={"scope": "all"})

    assert response.status_code == 200
    assert response.json()["cleared"] == 1


def test_api_settings_are_persisted_for_next_start(tmp_path) -> None:
    store = RuntimeSettingsStore(tmp_path / "settings.json")
    initial = BridgeSettings(connect_on_start=False)
    app = create_app(initial, settings_store=store)
    with TestClient(app) as client:
        response = client.post(
            "/api/settings",
            json={
                "internet_enabled": True,
                "youtube_enabled": True,
                "interactive_music_enabled": True,
                "brave_api_key": "persisted-test-key",
            },
        )

    loaded = store.load(BridgeSettings(connect_on_start=False))
    assert response.status_code == 200
    assert loaded.internet_enabled is True
    assert loaded.youtube_enabled is True
    assert loaded.interactive_music_enabled is True
    assert loaded.brave_api_key is not None
    assert loaded.brave_api_key.get_secret_value() == "persisted-test-key"


def test_mock_events_enter_feed_and_question_queue_while_paused() -> None:
    app = create_app(BridgeSettings(connect_on_start=False))
    with TestClient(app) as client:
        client.post("/api/control/pause", json={"paused": True})
        response = client.post(
            "/api/mock/event",
            json={
                "event_type": "chat_message",
                "display_name": "Demo",
                "user_id": "demo-user",
                "message": "Was hältst du davon?",
            },
        )
        queue = client.get("/api/queue")
        events = client.get("/api/events")

    assert response.status_code == 202
    assert queue.json()[0]["message"] == "Was hältst du davon?"
    assert events.json()[0]["is_question"] is True


def test_clear_endpoint_removes_paused_queue() -> None:
    app = create_app(BridgeSettings(connect_on_start=False))
    with TestClient(app) as client:
        client.post("/api/control/pause", json={"paused": True})
        client.post(
            "/api/mock/event",
            json={"event_type": "chat_message", "display_name": "Demo", "message": "Hallo"},
        )
        cleared = client.post("/api/control/clear")
        queue = client.get("/api/queue")

    assert cleared.status_code == 200
    assert cleared.json() == {"cleared": 1}
    assert queue.json() == []


def test_settings_endpoint_never_returns_api_keys() -> None:
    app = create_app(BridgeSettings(connect_on_start=False))
    with TestClient(app) as client:
        response = client.post(
            "/api/settings",
            json={"llm_api_key": "top-secret", "brave_api_key": "search-secret"},
        )
        fetched = client.get("/api/settings")

    assert response.status_code == 200
    assert fetched.json()["llm_api_key_configured"] is True
    assert fetched.json()["brave_api_key_configured"] is True
    assert "top-secret" not in response.text
    assert "top-secret" not in fetched.text
    assert "search-secret" not in response.text
    assert "search-secret" not in fetched.text


def test_youtube_search_endpoint_uses_backend_client() -> None:
    app = create_app(
        BridgeSettings(
            connect_on_start=False,
            internet_enabled=True,
            youtube_enabled=True,
            brave_api_key="test-token",
        )
    )
    with TestClient(app) as client:
        app.state.service.search_factory = lambda api_key, timeout: APISearchClient()
        response = client.post(
            "/api/search",
            json={"query": "NOEMA Musik", "kind": "youtube"},
        )

    assert response.status_code == 200
    assert response.json()["results"][0]["video_id"] == "dQw4w9WgXcQ"


def test_llm_diagnostic_endpoint() -> None:
    app = create_app(BridgeSettings(connect_on_start=False, model="api-test-model"))
    with TestClient(app) as client:
        app.state.service.provider_factory = lambda config: APIDiagnosticProvider()
        response = client.post("/api/diagnostics/llm")

    assert response.status_code == 200
    assert response.json()["model"] == "api-test-model"
    assert response.json()["answer"] == "Diagnose erfolgreich."


def test_mock_donut_is_exposed_as_spotlight_event() -> None:
    app = create_app(BridgeSettings(connect_on_start=False))
    with TestClient(app) as client:
        response = client.post(
            "/api/mock/event",
            json={
                "event_type": "gift",
                "display_name": "Supporter",
                "user_id": "supporter-1",
                "gift_name": "Donut",
                "diamond_count": 30,
            },
        )
        events = client.get("/api/events")

    assert response.status_code == 202
    assert events.json()[0]["gift_tier"] == "spotlight"

def test_youtube_api_returns_unverified_candidates_with_spotify_disabled() -> None:
    app = create_app(BridgeSettings(
        connect_on_start=False, internet_enabled=True, youtube_enabled=True,
        brave_api_key="test", music_backend="youtube", spotify_enabled=False,
        spotify_refresh_token="stale-token",
    ))
    with TestClient(app) as client:
        app.state.service.search_factory = lambda *args: APISearchClient()
        def forbidden(*args):
            raise AssertionError("Spotify must not be contacted")
        app.state.service.spotify_factory = forbidden
        response = client.post("/api/search", json={"query": "NOEMA Musik", "kind": "youtube"})
        assert response.status_code == 200
        assert response.json()["results"][0]["playback_status"] == "unverified"
        assert app.state.service.last_search_error is None
