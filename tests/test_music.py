from app.music import MusicCommand, extract_music_request, parse_music_command


def test_detects_german_and_english_music_requests() -> None:
    assert extract_music_request("Spiel bitte Chillout-Musik auf YouTube") == "Chillout-Musik"
    assert (
        extract_music_request("Kannst du bitte Lo-Fi Music auf YouTube spielen?")
        == "Lo-Fi Music"
    )
    assert extract_music_request("Play synthwave music") == "synthwave music"
    assert extract_music_request("Wechsel die Musik") == "Musik"
    assert extract_music_request("Bitte Musik wechseln") == "Musik"
    assert extract_music_request("Spiele Drive") == "Drive"
    assert extract_music_request("spiel mal Nightcall") == "Nightcall"
    assert extract_music_request("Play Nightcall") == "Nightcall"


def test_does_not_turn_discussion_or_control_commands_into_requests() -> None:
    assert extract_music_request("Welche Musik magst du?") is None
    assert extract_music_request("Pause die Musik") is None
    assert extract_music_request("Mach die Musik leiser") is None
    assert extract_music_request("Tolles Spiel") is None


def test_music_query_is_bounded() -> None:
    query = extract_music_request("Spiel Musik " + ("lang " * 100))
    assert query is not None
    assert len(query) <= 120


def test_parses_explicit_viewer_music_commands() -> None:
    assert parse_music_command("/musik Daft Punk") == MusicCommand("request", "Daft Punk")
    assert parse_music_command("/album Daft Punk Discovery") == MusicCommand(
        "album", "Daft Punk Discovery"
    )
    assert parse_music_command("/pause") == MusicCommand("pause")
    assert parse_music_command(" /weiter ") == MusicCommand("resume")
    assert parse_music_command("/skip") == MusicCommand("skip")
    assert parse_music_command("/lauter") == MusicCommand("volume_up")
    assert parse_music_command("/leiser") == MusicCommand("volume_down")


def test_rejects_unknown_or_embedded_slash_commands() -> None:
    assert parse_music_command("Hallo /pause") is None
    assert parse_music_command("/unbekannt") is None


def test_requested_song_and_discovery_commands_preserve_query() -> None:
    assert extract_music_request("spiele 80er best of") == "80er best of"
    assert extract_music_request("spiele The Final Countdown") == "The Final Countdown"
    assert parse_music_command("/musik Nightcall") == MusicCommand("request", "Nightcall")
