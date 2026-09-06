import asyncio
from datetime import datetime, timezone

from app.memory import ConversationTurn, MemoryManager, stable_user_hash


def turn(user_id: str, name: str, message: str, answer: str) -> ConversationTurn:
    return ConversationTurn(
        name, message, answer, datetime(2026, 8, 10, tzinfo=timezone.utc), user_id
    )


def test_same_display_name_different_ids_stay_separate(tmp_path) -> None:
    async def exercise():
        memory = MemoryManager(tmp_path)
        await memory.start()
        await memory.record_turn(turn("peter", "Alex", "Hamburg?", "Regen."))
        await memory.record_turn(turn("sandra", "Alex", "Chemnitz?", "Sonne."))
        await memory.flush()
        return await memory.context_for("peter", "Alex"), await memory.context_for("sandra", "Alex")

    peter, sandra = asyncio.run(exercise())
    assert peter.turns[0].message == "Hamburg?"
    assert sandra.turns[0].message == "Chemnitz?"
    assert stable_user_hash("peter") != stable_user_hash("sandra")


def test_persistent_memory_lazy_loads_after_restart(tmp_path) -> None:
    async def exercise():
        first = MemoryManager(tmp_path)
        await first.start()
        await first.record_turn(turn("sandra", "Sandra", "Wetter in Chemnitz?", "Morgen sonnig."))
        await first.close()
        second = MemoryManager(tmp_path)
        await second.start()
        assert second.active_users == 0
        context = await second.context_for("sandra", "Sandra")
        return second, context

    second, context = asyncio.run(exercise())
    assert second.active_users == 1
    assert context.turns[0].message == "Wetter in Chemnitz?"


def test_active_clear_keeps_disk_and_all_clear_removes_it(tmp_path) -> None:
    async def exercise():
        memory = MemoryManager(tmp_path)
        await memory.start()
        await memory.record_turn(turn("sandra", "Sandra", "Hallo", "Hallo!"))
        await memory.flush()
        assert await memory.clear("active") == 1
        restored = await memory.context_for("sandra", "Sandra")
        removed = await memory.clear("all")
        return restored, removed, list((tmp_path / "users").glob("*.md"))

    restored, removed, files = asyncio.run(exercise())
    assert len(restored.turns) == 1
    assert removed == 1
    assert files == []


def test_memory_filename_is_hash_not_display_name(tmp_path) -> None:
    async def exercise():
        memory = MemoryManager(tmp_path)
        await memory.record_turn(turn("stable-id", "../../Sandra", "Hallo", "Hallo!"))
        await memory.flush()

    asyncio.run(exercise())
    files = list((tmp_path / "users").glob("*.md"))
    assert [item.name for item in files] == [f"{stable_user_hash('stable-id')}.md"]
