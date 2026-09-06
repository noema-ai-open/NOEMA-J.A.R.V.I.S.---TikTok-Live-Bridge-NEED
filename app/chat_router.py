from __future__ import annotations

import re
from enum import Enum

from app.music import parse_music_command
from app.question_detection import is_question


class ChatIntent(str, Enum):
    DIRECT_COMMAND = "DIRECT_COMMAND"
    DIRECT_QUESTION = "DIRECT_QUESTION"
    FOLLOW_UP = "FOLLOW_UP"
    MUSIC_REQUEST = "MUSIC_REQUEST"
    GENERAL_QUESTION = "GENERAL_QUESTION"
    CHAT = "CHAT"
    NOISE = "NOISE"


INTENT_PRIORITY = {
    ChatIntent.DIRECT_COMMAND: 100,
    ChatIntent.DIRECT_QUESTION: 90,
    ChatIntent.FOLLOW_UP: 85,
    ChatIntent.MUSIC_REQUEST: 80,
    ChatIntent.GENERAL_QUESTION: 60,
    ChatIntent.CHAT: 30,
    ChatIntent.NOISE: 0,
}

_NOISE = {"lol", "haha", "hahaha", "ok", "okay", "ja", "ne", "nee", "xd", "k", "mhm"}
_DIRECT = re.compile(r"^(?:@?j\.?a\.?r\.?v\.?i\.?s\.?|@?jarvis|@?noema)\b", re.I)
_FOLLOW_UP = re.compile(
    r"^(?:und\s+)?(?:morgen|übermorgen|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|dort|dann|danach|warum|wieso|wie viel|wieviel|welche|welcher|welches)\b",
    re.I,
)


def route_chat(message: str, *, has_user_history: bool = False) -> ChatIntent:
    text = " ".join(message.strip().split())
    lowered = text.casefold()
    if not text:
        return ChatIntent.NOISE
    if parse_music_command(text) is not None:
        return ChatIntent.MUSIC_REQUEST
    if lowered.startswith("/frage"):
        return ChatIntent.DIRECT_COMMAND
    if text.startswith("/"):
        return ChatIntent.DIRECT_COMMAND
    if _is_noise(text, lowered):
        return ChatIntent.NOISE
    if _DIRECT.match(text) and is_question(text):
        return ChatIntent.DIRECT_QUESTION
    if has_user_history and len(text) <= 80 and (_FOLLOW_UP.match(text) or is_question(text)):
        return ChatIntent.FOLLOW_UP
    if is_question(text):
        return ChatIntent.GENERAL_QUESTION
    return ChatIntent.CHAT


def _is_noise(text: str, lowered: str) -> bool:
    if lowered in _NOISE:
        return True
    if not re.search(r"[\wäöüß]", text, re.I):
        return True
    compact = re.sub(r"\s+", "", lowered)
    if len(compact) > 4 and len(set(compact)) <= 2:
        return True
    words = lowered.split()
    return len(words) >= 4 and len(set(words)) == 1
