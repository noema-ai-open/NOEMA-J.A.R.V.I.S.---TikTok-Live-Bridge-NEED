from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


MusicAction = Literal["request", "album", "pause", "resume", "skip", "volume_up", "volume_down"]


@dataclass(frozen=True, slots=True)
class MusicCommand:
    action: MusicAction
    query: str | None = None


_SLASH_COMMAND = re.compile(
    r"^\s*/(musik|album|pause|weiter|skip|lauter|leiser)\b(?:\s+(.+?))?\s*$",
    re.IGNORECASE,
)


_CONTROL_ONLY = re.compile(
    r"\b(?:stop|stopp|pause|weiter|resume|lauter|leiser|volume)\b",
    re.IGNORECASE,
)
_PLAY_REQUEST = re.compile(
    r"\b(?:spiel(?:e|en)?|abspielen|starte|play|mach|wechsel(?:e|n)?|wechsle|ändere)\b",
    re.IGNORECASE,
)
_MUSIC_CONTEXT = re.compile(
    r"\b(?:musik|music|song|lied|track|playlist|radio|youtube)\b",
    re.IGNORECASE,
)
_DIRECT_PLAY_REQUEST = re.compile(
    r"^\s*(?:@?j\.?a\.?r\.?v\.?i\.?s\.?,?\s*)?"
    r"(?:(?:kannst|könntest|würdest)\s+du\s+|(?:can|could|would)\s+you\s+)?"
    r"(?:(?:bitte|please)\s+)?"
    r"(?:spiel(?:e|en)?|starte|play)\s+(?:(?:bitte|please|mal)\s+)?\S+",
    re.IGNORECASE,
)
_QUESTION_LEAD = re.compile(
    r"^\s*(?:@?j\.?a\.?r\.?v\.?i\.?s\.?,?\s*)?"
    r"(?:(?:kannst|könntest|würdest)\s+du|(?:can|could|would)\s+you)\s+"
    r"(?:(?:bitte|please)\s+)?",
    re.IGNORECASE,
)
_LEADING_FILLER = re.compile(
    r"^\s*(?:@?j\.?a\.?r\.?v\.?i\.?s\.?,?\s*)?"
    r"(?:(?:kannst|könntest|würdest|can|could|would)\s+du\s+)?"
    r"(?:bitte\s+)?(?:spiel(?:e)?|spiele|starte|play|mach|wechsel(?:e)?|wechsle|ändere)\s+"
    r"(?:(?:bitte|mal)\s+)?",
    re.IGNORECASE,
)
_TRAILING_FILLER = re.compile(
    r"\s+(?:auf\s+youtube\s+)?(?:abspielen|spielen|starten|wechseln|ändern|an)\s*[?!.]*$",
    re.IGNORECASE,
)


def parse_music_command(message: str) -> MusicCommand | None:
    """Parse the small, explicit set of viewer-facing media commands."""
    match = _SLASH_COMMAND.match(message)
    if match is None:
        return None
    command = match.group(1).lower()
    argument = " ".join((match.group(2) or "").strip().split())
    if command == "musik":
        return MusicCommand("request", argument[:120] or None)
    if command == "album":
        return MusicCommand("album", argument[:120] or None)
    actions: dict[str, MusicAction] = {
        "pause": "pause",
        "weiter": "resume",
        "skip": "skip",
        "lauter": "volume_up",
        "leiser": "volume_down",
    }
    return MusicCommand(actions[command])


def extract_music_request(message: str) -> str | None:
    """Return a bounded search query only for an explicit music play request."""
    cleaned = " ".join(message.strip().split())
    if not cleaned or _CONTROL_ONLY.search(cleaned):
        return None
    if not _PLAY_REQUEST.search(cleaned):
        return None

    # A direct imperative such as "spiele Drive" or "play Nightcall" already
    # carries enough media intent. Requiring an additional word such as
    # "Musik" caused normal viewer song requests to fall through to the LLM.
    if not _MUSIC_CONTEXT.search(cleaned) and not _DIRECT_PLAY_REQUEST.search(cleaned):
        return None

    query = _QUESTION_LEAD.sub("", cleaned)
    query = _LEADING_FILLER.sub("", query)
    query = _TRAILING_FILLER.sub("", query)
    query = re.sub(r"\b(?:auf\s+youtube|youtube)\b", "", query, flags=re.IGNORECASE)
    query = re.sub(r"\bbitte\b", "", query, flags=re.IGNORECASE)
    query = re.sub(r"^die\s+", "", query, flags=re.IGNORECASE)
    query = re.sub(
        r"^(?:musik|music|song|lied|track)\s+(?=\S)",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = " ".join(query.strip(" ?!.,-").split())
    if not query:
        return None
    return query[:120]
