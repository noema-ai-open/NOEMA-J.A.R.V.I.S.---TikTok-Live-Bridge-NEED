import asyncio
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.spotify import SpotifyConnectClient, SpotifyError, create_oauth_request


def test_pkce_authorization_url_uses_exact_loopback_redirect_and_scopes() -> None:
    redirect_uri = "http://127.0.0.1:8770/api/spotify/callback"
    request = create_oauth_request("client-id", redirect_uri)
    parsed = urlparse(request.url)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "accounts.spotify.com"
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == [redirect_uri]
    assert query["code_challenge_method"] == ["S256"]
    assert "user-read-playback-state" in query["scope"][0]
    assert "user-modify-playback-state" in query["scope"][0]
    assert len(request.verifier) >= 43
    assert request.state


def test_status_refreshes_token_and_returns_private_playback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.spotify.com":
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        if request.url.path == "/v1/me/player/devices":
            return httpx.Response(200, json={"devices": [{"id": "pc", "name": "WK02", "type": "Computer", "is_active": True, "is_restricted": False}]})
        if request.url.path == "/v1/me/player":
            return httpx.Response(200, json={
                "is_playing": True,
                "device": {"id": "pc", "name": "WK02", "volume_percent": 35},
                "item": {"name": "Private Track", "artists": [{"name": "Artist"}]},
            })
        raise AssertionError(request.url)

    client = SpotifyConnectClient(
        "client-id", "refresh", transport=httpx.MockTransport(handler)
    )
    status = asyncio.run(client.status())

    assert status["connected"] is True
    assert status["track"] == "Private Track"
    assert status["artists"] == "Artist"
    assert status["device"] == "WK02"


def test_search_and_play_uses_active_connect_device() -> None:
    played: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.spotify.com":
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        if request.url.path == "/v1/search":
            assert request.url.params["q"] == "Synthwave"
            return httpx.Response(200, json={"tracks": {"items": [{"uri": "spotify:track:one"}]}})
        if request.url.path == "/v1/me/player/play":
            played.append({"device_id": request.url.params.get("device_id")})
            return httpx.Response(204)
        if request.url.path == "/v1/me/player/devices":
            return httpx.Response(200, json={"devices": []})
        if request.url.path == "/v1/me/player":
            return httpx.Response(200, json={
                "is_playing": True,
                "device": {"id": "pc", "name": "WK02", "volume_percent": 40, "is_restricted": False},
                "item": {"name": "Synthwave", "artists": []},
            })
        raise AssertionError(request.url)

    client = SpotifyConnectClient(
        "client-id", "refresh", transport=httpx.MockTransport(handler)
    )
    status = asyncio.run(client.control("play", query="Synthwave"))

    assert played == [{"device_id": "pc"}]
    assert status["track"] == "Synthwave"


def test_search_and_play_album_uses_spotify_context() -> None:
    playback_bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.spotify.com":
            return httpx.Response(200, json={"access_token": "access", "expires_in": 3600})
        if request.url.path == "/v1/search":
            assert request.url.params["q"] == "Daft Punk Discovery"
            assert request.url.params["type"] == "album"
            return httpx.Response(
                200, json={"albums": {"items": [{"uri": "spotify:album:discovery"}]}}
            )
        if request.url.path == "/v1/me/player/play":
            playback_bodies.append(json.loads(request.content))
            return httpx.Response(204)
        if request.url.path == "/v1/me/player/devices":
            return httpx.Response(200, json={"devices": []})
        if request.url.path == "/v1/me/player":
            return httpx.Response(200, json={
                "is_playing": True,
                "device": {"id": "pc", "name": "WK02", "volume_percent": 40, "is_restricted": False},
                "item": {"name": "One More Time", "artists": [{"name": "Daft Punk"}]},
            })
        raise AssertionError(request.url)

    client = SpotifyConnectClient(
        "client-id", "refresh", transport=httpx.MockTransport(handler)
    )
    status = asyncio.run(client.control("play_album", query="Daft Punk Discovery"))

    assert playback_bodies == [{"context_uri": "spotify:album:discovery"}]
    assert status["track"] == "One More Time"


def test_spotify_network_failure_is_bounded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("offline", request=request)

    client = SpotifyConnectClient(
        "client-id", "refresh", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(SpotifyError, match="Tokenserver"):
        asyncio.run(client.status())
