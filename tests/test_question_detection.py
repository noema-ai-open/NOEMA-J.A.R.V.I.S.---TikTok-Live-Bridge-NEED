import pytest

from app.question_detection import is_question


@pytest.mark.parametrize(
    "message",
    [
        "Wie heißt das Spiel?",
        "Was hältst du davon?",
        "where are you from?",
        "warum machst du das",
        "Hey Noema, kannst du mich sehen",
        "Hallo wieviel Bundesländer gibt es",
        "Wieviele Zuschauer sind online",
        "what game is this",
        "/frage Welches Spiel ist das",
    ],
)
def test_detects_questions(message: str) -> None:
    assert is_question(message)


@pytest.mark.parametrize("message", ["Tolles Spiel", "Hallo zusammen", "", "Das ist warum ich spiele"])
def test_rejects_normal_comments(message: str) -> None:
    assert not is_question(message)
