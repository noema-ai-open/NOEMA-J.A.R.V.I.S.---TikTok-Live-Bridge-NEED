from datetime import datetime, timezone

import pytest

from app.models import JarvisState, QueuedQuestion
from app.resilient_service import LiveAIService
from app.service import LiveAIService as BaseLiveAIService
from app.settings import BridgeSettings


@pytest.mark.asyncio
async def test_provider_exhaustion_does_not_pause_entire_live_session(monkeypatch) -> None:
    async def simulated_base_failure(self, question: QueuedQuestion) -> None:
        self.questions.requeue(question)
        self.paused = True
        self.current_question = None
        self.current_answer = ""
        self.state = JarvisState.ERROR
        self.last_error = "provider failed"

    monkeypatch.setattr(BaseLiveAIService, "_answer", simulated_base_failure)
    service = LiveAIService(BridgeSettings(connect_on_start=False))
    question = QueuedQuestion(
        event_id="evt-failed",
        event_timestamp=datetime.now(timezone.utc),
        user_id="viewer-1",
        display_name="Viewer",
        message="Testfrage",
    )

    await service._answer(question)

    assert service.paused is False
    assert service.state == JarvisState.ERROR
    assert service.last_error == "provider failed"
    assert all(item.event_id != question.event_id for item in service.questions.snapshot())
