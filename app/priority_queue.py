from __future__ import annotations

from datetime import timedelta

from app.models import GiftInfo, QueuedQuestion, TikTokEvent


class QuestionQueue:
    """Bounded gift-aware queue with immutable source chronology."""

    def __init__(
        self,
        max_size: int = 100,
        gift_boost: int = 100,
        spotlight_gift_boost: int = 200,
        gift_question_window_seconds: float = 90.0,
        max_pending_gifts: int = 500,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be positive")
        self.max_size = max_size
        self.gift_boost = gift_boost
        self.spotlight_gift_boost = spotlight_gift_boost
        self.gift_question_window = timedelta(seconds=gift_question_window_seconds)
        self.max_pending_gifts = max_pending_gifts
        self._items: list[QueuedQuestion] = []
        self._pending_gifts: dict[str, GiftInfo] = {}
        self._sequence = 0

    def __len__(self) -> int:
        return len(self._items)

    def snapshot(self) -> list[QueuedQuestion]:
        return sorted(self._items, key=lambda item: (-item.priority, item.sequence))

    def add(
        self,
        event: TikTokEvent,
        *,
        is_question: bool = True,
        priority: int = 0,
        priority_reason: str | None = None,
        intent: str = "GENERAL_QUESTION",
    ) -> QueuedQuestion | None:
        if len(self._items) >= self.max_size or not event.message:
            return None
        music_request = event.metadata.get("music_request")
        question = QueuedQuestion(
            event_id=event.event_id,
            event_timestamp=event.timestamp,
            user_id=event.user.user_id,
            display_name=event.user.display_name,
            message=event.message,
            is_question=is_question,
            priority=priority,
            priority_reason=priority_reason or ("question" if is_question else "chat"),
            music_request=music_request if isinstance(music_request, str) else None,
            intent=intent,
            sequence=self._sequence,
        )
        self._sequence += 1
        self._items.append(question)
        gift = self._pending_gifts.pop(question.user_id, None)
        if gift is not None:
            age = question.event_timestamp - gift.timestamp
            if timedelta(0) <= age <= self.gift_question_window:
                self._apply_gift(question, gift)
        return question

    def pop(self) -> QueuedQuestion | None:
        if not self._items:
            return None
        selected = min(self._items, key=lambda item: (-item.priority, item.sequence))
        self._items.remove(selected)
        return selected

    def requeue(self, question: QueuedQuestion) -> None:
        if all(item.event_id != question.event_id for item in self._items):
            self._items.append(question)

    def boost_for_gift(self, gift_event: TikTokEvent) -> QueuedQuestion | None:
        candidates = [item for item in self._items if item.user_id == gift_event.user.user_id]
        gift = GiftInfo.from_event(gift_event)
        if not candidates:
            self._pending_gifts[gift_event.user.user_id] = gift
            while len(self._pending_gifts) > self.max_pending_gifts:
                oldest_user = next(iter(self._pending_gifts))
                self._pending_gifts.pop(oldest_user)
            return None
        selected = min(candidates, key=lambda item: item.sequence)
        self._apply_gift(selected, gift)
        return selected

    def _apply_gift(self, selected: QueuedQuestion, gift: GiftInfo) -> None:
        boost = (
            self.spotlight_gift_boost if gift.tier == "spotlight" else self.gift_boost
        )
        selected.priority += boost
        selected.priority_reason = f"gift:{gift.tier}:{gift.name or 'unknown'}"
        selected.gift = gift

    def clear(self) -> int:
        count = len(self._items)
        self._items.clear()
        self._pending_gifts.clear()
        return count
