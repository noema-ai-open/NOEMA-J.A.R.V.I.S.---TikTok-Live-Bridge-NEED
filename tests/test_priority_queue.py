from app.priority_queue import QuestionQueue


def test_queue_keeps_stable_order_for_equal_priority(event_factory) -> None:
    queue = QuestionQueue(max_size=5)
    first = queue.add(event_factory(message="Was ist eins?"))
    second = queue.add(event_factory(message="Was ist zwei?"))

    assert queue.pop() == first
    assert queue.pop() == second


def test_gift_boost_promotes_oldest_open_question_without_changing_source_data(event_factory) -> None:
    queue = QuestionQueue(max_size=5, gift_boost=100)
    other = queue.add(event_factory(user_id="other", message="Was ist neu?"))
    target = queue.add(event_factory(user_id="fan", message="Wie geht es dir?"))
    original_timestamp = target.event_timestamp
    gift = event_factory(
        event_type="gift",
        user_id="fan",
        message=None,
        metadata={"gift_name": "Rose", "repeat_count": 2, "diamond_count": 1},
    )

    boosted = queue.boost_for_gift(gift)

    assert boosted is target
    assert boosted.priority == 100
    assert boosted.priority_reason == "gift:supporter:Rose"
    assert boosted.gift.name == "Rose"
    assert boosted.gift.tier == "supporter"
    assert boosted.event_timestamp == original_timestamp
    assert queue.pop() is target
    assert queue.pop() is other


def test_gift_does_not_affect_other_users(event_factory) -> None:
    queue = QuestionQueue()
    question = queue.add(event_factory(user_id="a"))
    gift = event_factory(event_type="gift", user_id="b", message=None)

    assert queue.boost_for_gift(gift) is None
    assert question.priority == 0


def test_donut_gets_spotlight_boost_without_changing_source_order(event_factory) -> None:
    queue = QuestionQueue(max_size=5, gift_boost=100, spotlight_gift_boost=200)
    rose_question = queue.add(
        event_factory(user_id="rose-fan", message="Was ist eine Rose?")
    )
    donut_question = queue.add(
        event_factory(user_id="donut-fan", message="Was ist ein Donut?")
    )
    rose_sequence = rose_question.sequence
    donut_sequence = donut_question.sequence

    queue.boost_for_gift(
        event_factory(
            event_type="gift",
            user_id="rose-fan",
            message=None,
            metadata={"gift_name": "Rose", "diamond_count": 1},
        )
    )
    boosted = queue.boost_for_gift(
        event_factory(
            event_type="gift",
            user_id="donut-fan",
            message=None,
            metadata={"gift_name": "Donut", "diamond_count": 30},
        )
    )

    assert boosted.priority == 200
    assert boosted.priority_reason == "gift:spotlight:Donut"
    assert boosted.gift.tier == "spotlight"
    assert rose_question.sequence == rose_sequence
    assert donut_question.sequence == donut_sequence
    assert queue.pop() is donut_question
    assert queue.pop() is rose_question


def test_gift_before_question_is_applied_within_recent_window(event_factory) -> None:
    queue = QuestionQueue(gift_question_window_seconds=90)
    gift = event_factory(
        event_type="gift",
        user_id="early-supporter",
        message=None,
        metadata={"gift_name": "Donut"},
    )

    assert queue.boost_for_gift(gift) is None
    question = queue.add(
        event_factory(
            user_id="early-supporter", message="Kannst du meine Frage beantworten?"
        )
    )

    assert question.priority == 200
    assert question.gift.name == "Donut"
    assert question.priority_reason == "gift:spotlight:Donut"


def test_queue_is_bounded(event_factory) -> None:
    queue = QuestionQueue(max_size=1)
    assert queue.add(event_factory()) is not None
    assert queue.add(event_factory()) is None
