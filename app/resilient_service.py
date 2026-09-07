from __future__ import annotations

from app.models import JarvisState, QueuedQuestion
from app.service import LiveAIService as BaseLiveAIService


class LiveAIService(BaseLiveAIService):
    """Live service with non-blocking recovery after provider exhaustion.

    The base service intentionally requeues the active question and pauses the
    whole processor when every configured provider fails.  During a live show
    that turns a transient LLM outage into a permanent stop until the operator
    notices the pause.  This adapter keeps the error visible but discards only
    the failed question and lets later viewer requests continue normally.
    """

    async def _answer(self, question: QueuedQuestion) -> None:
        await super()._answer(question)

        if not (self.paused and self.state == JarvisState.ERROR):
            return

        # Provider-exhaustion in the base implementation requeues exactly the
        # question that just failed. Runtime errors and manual pause do not.
        before = len(self.questions._items)
        self.questions._items[:] = [
            item for item in self.questions._items if item.event_id != question.event_id
        ]
        if len(self.questions._items) == before:
            return

        self.paused = False
        self.bus.publish({"type": "queue", "queue": self.queue_payload()})
        if len(self.questions):
            self._wake.set()
        self._publish_status()
