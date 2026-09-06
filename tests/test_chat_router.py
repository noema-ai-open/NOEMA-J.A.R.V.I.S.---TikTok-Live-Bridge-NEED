from app.chat_router import ChatIntent, route_chat


def test_noise_is_not_routed_to_llm() -> None:
    assert route_chat("lol") is ChatIntent.NOISE
    assert route_chat("😂") is ChatIntent.NOISE


def test_direct_jarvis_question_is_detected() -> None:
    assert route_chat("Jarvis, wie wird morgen das Wetter?") is ChatIntent.DIRECT_QUESTION


def test_follow_up_requires_same_user_history() -> None:
    assert route_chat("Und Dienstag?", has_user_history=True) is ChatIntent.FOLLOW_UP
    assert route_chat("Und Dienstag?", has_user_history=False) is ChatIntent.GENERAL_QUESTION
