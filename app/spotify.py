from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode

import httpx


SPOTIFY_SCOPES = "user-read-playback-state user-modify-playback-state"
SpotifyControl = Literal[
    "play", "play_album", "pause", "resume", "skip", "volume_up", "volume_down"
]


class SpotifyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SpotifyOAuthRequest:
    url: str
    state: str
    verifier: str


def create_oauth_request(client_id: str, redirect_uri: str) -> SpotifyOAuthRequest:
    verifier = secrets.token_urlsafe(72)[:96]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    state = secrets.token_urlsafe(32)
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SPOTIFY_SCOPES,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
        }
    )
    return SpotifyOAuthRequest(
        url=f"https://accounts.spotify.com/authorize?{query}",
        state=state,
        verifier=verifier,
    )


class SpotifyConnectClient:
    """Minimal private Spotify Connect controller using OAuth PKCE."""

    def __init__(
        self,
        client_id: str,
        refresh_token: str | None,
        *,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.client_id = client_id
        self.refresh_token = refresh_token
        self.timeout = timeout
        self.transport = transport
        self._access_token: str | None = None
        self._expires_at = 0.0

    async def exchange_code(
        self, code: str, verifier: str, redirect_uri: str
    ) -> str:
        try:
            async with self._http() as client:
                response = await client.post(
                    "https://accounts.spotify.com/api/token",
                    data={
                        "client_id": self.client_id,
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "code_verifier": verifier,
                    },
                )
        except httpx.HTTPError as exc:
            raise SpotifyError("Spotify-Anmeldung ist nicht erreichbar") from exc
        payload = self._payload(response, "Spotify-Anmeldung fehlgeschlagen")
        refresh_token = payload.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise SpotifyError("Spotify hat kein Refresh-Token geliefert")
        self.refresh_token = refresh_token
        self._accept_access_token(payload)
        return refresh_token

    async def status(self) -> dict[str, object]:
        playback = await self._request("GET", "/v1/me/player", allow_empty=True)
        devices_payload = await self._request("GET", "/v1/me/player/devices")
        devices = devices_payload.get("devices", []) if isinstance(devices_payload, dict) else []
        item = playback.get("item") if isinstance(playback, dict) else None
        artists = item.get("artists", []) if isinstance(item, dict) else []
        device = playback.get("device") if isinstance(playback, dict) else None
        return {
            "connected": True,
            "is_playing": bool(playback.get("is_playing")) if isinstance(playback, dict) else False,
            "track": item.get("name") if isinstance(item, dict) else None,
            "artists": ", ".join(
                artist.get("name", "") for artist in artists if isinstance(artist, dict)
            ),
            "device": device.get("name") if isinstance(device, dict) else None,
            "volume": device.get("volume_percent") if isinstance(device, dict) else None,
            "devices": [
                {
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "type": entry.get("type"),
                    "active": bool(entry.get("is_active")),
                    "restricted": bool(entry.get("is_restricted")),
                }
                for entry in devices
                if isinstance(entry, dict)
            ],
        }

    async def control(
        self, action: SpotifyControl, *, query: str | None = None
    ) -> dict[str, object]:
        device_id = await self._ensure_device()
        params = {"device_id": device_id} if device_id else None
        if action in {"play", "play_album"} and query:
            search_type = "album" if action == "play_album" else "track"
            search = await self._request(
                "GET",
                "/v1/search",
                params={"q": query, "type": search_type, "limit": 1},
            )
            result_key = "albums" if action == "play_album" else "tracks"
            items = ((search.get(result_key) or {}).get("items") or []) if isinstance(search, dict) else []
            if not items:
                noun = "Album" if action == "play_album" else "Titel"
                raise SpotifyError(f"Kein Spotify-{noun} gefunden")
            item = items[0]
            playback = (
                {"context_uri": item["uri"]}
                if action == "play_album"
                else {"uris": [item["uri"]]}
            )
            await self._request(
                "PUT", "/v1/me/player/play", params=params, json=playback
            )
        elif action in {"play", "resume"}:
            await self._request("PUT", "/v1/me/player/play", params=params)
        elif action == "pause":
            await self._request("PUT", "/v1/me/player/pause", params=params)
        elif action == "skip":
            await self._request("POST", "/v1/me/player/next", params=params)
        elif action in {"volume_up", "volume_down"}:
            playback = await self._request("GET", "/v1/me/player", allow_empty=True)
            device = playback.get("device") if isinstance(playback, dict) else None
            current = device.get("volume_percent") if isinstance(device, dict) else 50
            current = current if isinstance(current, int) else 50
            target = max(0, min(100, current + (10 if action == "volume_up" else -10)))
            await self._request(
                "PUT",
                "/v1/me/player/volume",
                params={"device_id": device_id, "volume_percent": target},
            )
        return await self.status()

    async def _ensure_device(self) -> str | None:
        playback = await self._request("GET", "/v1/me/player", allow_empty=True)
        active = playback.get("device") if isinstance(playback, dict) else None
        if isinstance(active, dict) and active.get("id") and not active.get("is_restricted"):
            return str(active["id"])
        devices_payload = await self._request("GET", "/v1/me/player/devices")
        devices = devices_payload.get("devices", []) if isinstance(devices_payload, dict) else []
        device = next(
            (
                entry
                for entry in devices
                if isinstance(entry, dict) and entry.get("id") and not entry.get("is_restricted")
            ),
            None,
        )
        if device is None:
            raise SpotifyError("Kein steuerbares Spotify-Connect-Gerät aktiv")
        device_id = str(device["id"])
        await self._request(
            "PUT", "/v1/me/player", json={"device_ids": [device_id], "play": False}
        )
        return device_id

    async def _token(self) -> str:
        if self._access_token and time.monotonic() < self._expires_at - 30:
            return self._access_token
        if not self.refresh_token:
            raise SpotifyError("Spotify ist noch nicht verbunden")
        try:
            async with self._http() as client:
                response = await client.post(
                    "https://accounts.spotify.com/api/token",
                    data={
                        "client_id": self.client_id,
                        "grant_type": "refresh_token",
                        "refresh_token": self.refresh_token,
                    },
                )
        except httpx.HTTPError as exc:
            raise SpotifyError("Spotify-Tokenserver ist nicht erreichbar") from exc
        payload = self._payload(response, "Spotify-Token konnte nicht erneuert werden")
        self._accept_access_token(payload)
        refreshed = payload.get("refresh_token")
        if isinstance(refreshed, str) and refreshed:
            self.refresh_token = refreshed
        return self._access_token or ""

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json: dict[str, object] | None = None,
        allow_empty: bool = False,
    ) -> dict[str, object]:
        token = await self._token()
        try:
            async with self._http() as client:
                response = await client.request(
                    method,
                    f"https://api.spotify.com{path}",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                    json=json,
                )
        except httpx.TimeoutException as exc:
            raise SpotifyError("Spotify-Anfrage hat das Zeitlimit überschritten") from exc
        except httpx.HTTPError as exc:
            raise SpotifyError("Spotify ist nicht erreichbar") from exc
        if response.status_code == 204 and allow_empty:
            return {}
        if response.status_code == 204:
            return {}
        return self._payload(response, "Spotify-Anfrage fehlgeschlagen")

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout, transport=self.transport)

    def _accept_access_token(self, payload: dict[str, object]) -> None:
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise SpotifyError("Spotify hat kein Access-Token geliefert")
        expires_in = payload.get("expires_in", 3600)
        self._access_token = access_token
        self._expires_at = time.monotonic() + float(expires_in)

    @staticmethod
    def _payload(response: httpx.Response, fallback: str) -> dict[str, object]:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.is_error:
            detail = payload.get("error_description") if isinstance(payload, dict) else None
            if not detail and isinstance(payload, dict):
                error = payload.get("error")
                detail = error.get("message") if isinstance(error, dict) else error
            raise SpotifyError(str(detail or f"{fallback} (HTTP {response.status_code})"))
        return payload if isinstance(payload, dict) else {}
