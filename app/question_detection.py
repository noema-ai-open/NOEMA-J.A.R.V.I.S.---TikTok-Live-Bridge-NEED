import re


_QUESTION_WORDS = {
    "wer", "wie", "wieviel", "wieviele", "was", "wann", "wo", "woher", "wohin", "warum", "wieso",
    "weshalb", "welche", "welcher", "welches", "kann", "kannst", "können",
    "hast", "habt", "ist", "sind", "darf", "soll", "würdest", "what", "when",
    "where", "why", "who", "which", "whose", "whom", "how", "can", "could",
    "would", "should", "do", "does", "did", "is", "are", "will",
}
_LEADING_FILLER = {"hey", "hi", "hallo", "noema", "jarvis", "bitte", "sag", "tell"}


def is_question(message: str) -> bool:
    """Fast deterministic TikTok question classification without another LLM."""
    text = " ".join(message.strip().lower().split())
    if not text:
        return False
    if re.match(r"^/frage(?:\s+\S|$)", text):
        return True
    if "?" in text:
        return True
    words = re.findall(r"[a-zäöüß']+", text)
    if not words or len(words) > 40:
        return False
    index = 0
    while index < min(3, len(words)) and words[index] in _LEADING_FILLER:
        index += 1
    return index < len(words) and words[index] in _QUESTION_WORDS
