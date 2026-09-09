import json

from app.settings import BridgeSettings
from app.settings_store import RuntimeSettingsStore


def test_runtime_settings_and_keys_survive_reload(tmp_path) -> None:
    path = tmp_path / "settings.json"
    store = RuntimeSettingsStore(path)
    configured = BridgeSettings(
        model="qwen/test",
        internet_enabled=True,
        youtube_enabled=True,
        interactive_music_enabled=True,
        music_rotation_enabled=False,
        music_request_cooldown=90,
        brave_api_key="test-brave-key",
        spotify_enabled=True,
        spotify_client_id="test-client-id",
        spotify_refresh_token="test-refresh-token",
    )

    store.save(configured)
    loaded = store.load(BridgeSettings())
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert loaded.model == "qwen/test"
    assert loaded.internet_enabled is True
    assert loaded.youtube_enabled is True
    assert loaded.interactive_music_enabled is True
    assert loaded.music_rotation_enabled is False
    assert loaded.music_request_cooldown == 90
    assert loaded.brave_api_key is not None
    assert loaded.brave_api_key.get_secret_value() == "test-brave-key"
    assert raw["brave_api_key"] == "test-brave-key"
    assert raw["music_rotation_enabled"] is False
    assert loaded.spotify_client_id == "test-client-id"
    assert loaded.spotify_refresh_token is not None
    assert loaded.spotify_refresh_token.get_secret_value() == "test-refresh-token"
    assert raw["spotify_refresh_token"] == "test-refresh-token"


def test_legacy_music_defaults_migrate_to_two_minutes(tmp_path) -> None:
    for legacy in (30.0, 300.0):
        path = tmp_path / f"settings-{int(legacy)}.json"
        path.write_text(
            json.dumps({"music_request_cooldown": legacy}),
            encoding="utf-8",
        )

        loaded = RuntimeSettingsStore(path).load(BridgeSettings())

        assert loaded.music_request_cooldown == 120.0


def test_custom_music_interval_is_preserved(tmp_path) -> None:
    path = tmp_path / "settings-custom.json"
    path.write_text(
        json.dumps({"music_request_cooldown": 75.0}),
        encoding="utf-8",
    )

    loaded = RuntimeSettingsStore(path).load(BridgeSettings())

    assert loaded.music_request_cooldown == 75.0


def test_invalid_settings_file_falls_back_without_crashing(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("not-json", encoding="utf-8")
    fallback = BridgeSettings(model="fallback-model")

    loaded = RuntimeSettingsStore(path).load(fallback)

    assert loaded is fallback
