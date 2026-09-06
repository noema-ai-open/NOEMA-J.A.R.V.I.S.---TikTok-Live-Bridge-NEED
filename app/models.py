from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class JarvisState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


class EventUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    display_name: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    is_moderator: bool = False
    is_subscriber: bool = False


class TikTokEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    platform: str = "tiktok"
    event_type: Literal["chat_message", "gift", "follow", "share", "status"]
    event_id: str = Field(min_length=1, max_length=300)
    timestamp: datetime
    user: EventUser
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @model_validator(mode="after")
    def chat_has_message(self) -> "TikTokEvent":
        if self.event_type == "chat_message" and not self.message:
            raise ValueError("chat_message events require a message")
        return self

    @classmethod
    def from_websocket_payload(cls, payload: object) -> "TikTokEvent | None":
        if not isinstance(payload, dict):
            raise ValueError("event payload must be an object")
        if payload.get("type") == "blocked":
            return None
        event_type = payload.get("event_type")
        if event_type not in {"chat_message", "gift", "follow", "share", "status"}:
            return None
        return cls.model_validate(payload)


class GiftInfo(BaseModel):
    name: str | None = None
    count: int | None = None
    diamonds: int | None = None
    tier: Literal["supporter", "spotlight"] = "supporter"
    event_id: str
    timestamp: datetime

    @classmethod
    def from_event(cls, event: TikTokEvent) -> "GiftInfo":
        metadata = event.metadata
        name = _text_or_none(metadata.get("gift_name"))
        return cls(
            name=name,
            count=_int_or_none(metadata.get("repeat_count") or metadata.get("count")),
            diamonds=_int_or_none(metadata.get("diamond_count")),
            tier=classify_gift(name),
            event_id=event.event_id,
            timestamp=event.timestamp,
        )


class QueuedQuestion(BaseModel):
    event_id: str
    event_timestamp: datetime
    user_id: str
    display_name: str
    message: str
    is_question: bool = True
    priority: int = 0
    priority_reason: str = "question"
    gift: GiftInfo | None = None
    music_request: str | None = None
    intent: str = "GENERAL_QUESTION"
    sequence: int = 0


def _text_or_none(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def classify_gift(name: str | None) -> Literal["supporter", "spotlight"]:
    normalized = (name or "").casefold()
    if "donut" in normalized or "doughnut" in normalized:
        return "spotlight"
    return "supporter"
