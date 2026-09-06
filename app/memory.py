from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import sys
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path


logger = logging.getLogger(__name__)
_TURN_PATTERN = re.compile(
    r"^### (?P<timestamp>[^\n]+)\nUSER:\n(?P<message>.*?)\n\nJARVIS:\n(?P<answer>.*?)(?=\n\n### |\Z)",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    display_name: str
    message: str
    answer: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: str = ""
    intent: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryContext:
    summary: str
    turns: tuple[ConversationTurn, ...]


@dataclass(slots=True)
class UserMemory:
    user_hash: str
    display_name: str
    turns: deque[ConversationTurn]
    last_used: datetime


def default_memory_root() -> Path:
    base = (
        Path(sys.executable).resolve().parent.parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent.parent
    )
    return base / "data" / "memory"


def stable_user_hash(user_id: str, display_name: str = "") -> str:
    stable = user_id.strip() or f"display:{display_name.strip().casefold()}"
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def _line(value: str, limit: int) -> str:
    return " ".join(value.replace("```", "'''").split())[:limit]


class MemoryManager:
    def __init__(
        self,
        root: Path | None = None,
        *,
        enabled: bool = True,
        recent_turns: int = 10,
        max_users_ram: int = 200,
        max_turns_per_user_disk: int = 100,
        retention_days: int = 30,
    ) -> None:
        self.root = (root or default_memory_root()).resolve()
        self.users_dir = self.root / "users"
        self.enabled = enabled
        self.recent_turns = recent_turns
        self.max_users_ram = max_users_ram
        self.max_turns_per_user_disk = max_turns_per_user_disk
        self.retention_days = retention_days
        self._users: OrderedDict[str, UserMemory] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._write_tasks: set[asyncio.Task[None]] = set()
        self.persistent_ok = True
        self.persistent_users = 0

    @property
    def active_users(self) -> int:
        return len(self._users)

    async def start(self) -> None:
        if not self.enabled:
            return
        await asyncio.to_thread(self._maintenance_sync)

    async def close(self) -> None:
        await self.flush()

    async def flush(self) -> None:
        if self._write_tasks:
            await asyncio.gather(*tuple(self._write_tasks), return_exceptions=True)

    async def context_for(self, user_id: str, display_name: str) -> MemoryContext:
        if not self.enabled:
            return MemoryContext("", ())
        memory = await self._get_or_load(user_id, display_name)
        turns = tuple(memory.turns)[-self.recent_turns :]
        older = tuple(memory.turns)[: -self.recent_turns]
        summary = self._summary(older)
        return MemoryContext(summary, turns)

    async def has_history(self, user_id: str, display_name: str) -> bool:
        return bool((await self.context_for(user_id, display_name)).turns)

    async def record_turn(self, turn: ConversationTurn) -> None:
        if not self.enabled:
            return
        memory = await self._get_or_load(turn.user_id, turn.display_name)
        memory.display_name = turn.display_name
        memory.last_used = turn.timestamp
        memory.turns.append(turn)
        self._users.move_to_end(memory.user_hash)
        self._evict_if_needed()
        task = asyncio.create_task(
            self._persist(memory), name=f"memory-write-{memory.user_hash}"
        )
        self._write_tasks.add(task)
        task.add_done_callback(self._write_tasks.discard)

    async def clear(self, scope: str, *, user_id: str | None = None) -> int:
        if scope == "active":
            count = len(self._users)
            self._users.clear()
            return count
        if scope == "user":
            if not user_id:
                raise ValueError("user_id is required for user memory clear")
            await self.flush()
            user_hash = stable_user_hash(user_id)
            self._users.pop(user_hash, None)
            removed = await asyncio.to_thread(self._remove_file, self._path(user_hash))
            if removed:
                self.persistent_users = max(0, self.persistent_users - 1)
            return int(removed)
        if scope == "all":
            await self.flush()
            self._users.clear()
            removed = await asyncio.to_thread(self._remove_all_sync)
            self.persistent_users = 0
            return removed
        raise ValueError("invalid memory clear scope")

    async def _get_or_load(self, user_id: str, display_name: str) -> UserMemory:
        user_hash = stable_user_hash(user_id, display_name)
        cached = self._users.get(user_hash)
        if cached is not None:
            cached.last_used = datetime.now(timezone.utc)
            cached.display_name = display_name
            self._users.move_to_end(user_hash)
            return cached
        memory = await asyncio.to_thread(
            self._load_sync, user_hash, user_id, display_name
        )
        self._users[user_hash] = memory
        self._evict_if_needed()
        return memory

    def _evict_if_needed(self) -> None:
        while len(self._users) > self.max_users_ram:
            self._users.popitem(last=False)

    async def _persist(self, memory: UserMemory) -> None:
        lock = self._locks.setdefault(memory.user_hash, asyncio.Lock())
        async with lock:
            try:
                snapshot = tuple(memory.turns)[-self.max_turns_per_user_disk :]
                existed = self._path(memory.user_hash).exists()
                await asyncio.to_thread(self._write_sync, memory, snapshot)
                if not existed:
                    self.persistent_users += 1
                logger.debug("memory persisted for user hash %s", memory.user_hash)
            except OSError:
                self.persistent_ok = False
                logger.exception("memory persistence failed for user hash %s", memory.user_hash)

    def _path(self, user_hash: str) -> Path:
        return self.users_dir / f"{user_hash}.md"

    def _load_sync(self, user_hash: str, user_id: str, display_name: str) -> UserMemory:
        path = self._path(user_hash)
        turns: deque[ConversationTurn] = deque(maxlen=self.max_turns_per_user_disk)
        last_used = datetime.now(timezone.utc)
        try:
            content = path.read_text(encoding="utf-8")
            name_match = re.search(r"^Letzter Anzeigename: (.*)$", content, re.MULTILINE)
            if name_match:
                display_name = name_match.group(1).strip() or display_name
            for match in _TURN_PATTERN.finditer(content):
                timestamp = datetime.fromisoformat(match.group("timestamp").strip())
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                turns.append(
                    ConversationTurn(
                        timestamp=timestamp,
                        user_id=user_id,
                        display_name=display_name,
                        message=match.group("message").strip(),
                        answer=match.group("answer").strip(),
                    )
                )
                last_used = timestamp
            logger.debug("memory loaded for user hash %s", user_hash)
        except FileNotFoundError:
            pass
        except (OSError, UnicodeError, ValueError):
            self.persistent_ok = False
            logger.warning("memory file ignored for user hash %s", user_hash)
        return UserMemory(user_hash, display_name, turns, last_used)

    def _write_sync(
        self, memory: UserMemory, turns: tuple[ConversationTurn, ...]
    ) -> None:
        self.users_dir.mkdir(parents=True, exist_ok=True)
        last_used = turns[-1].timestamp if turns else memory.last_used
        lines = [
            "# J.A.R.V.I.S. User Memory",
            "",
            f"User-ID-Hash: {memory.user_hash}",
            f"Letzter Anzeigename: {_line(memory.display_name, 200)}",
            f"Zuletzt aktiv: {last_used.isoformat()}",
            "",
            "## Memory Summary",
            "",
            self._summary(turns[: -self.recent_turns]) or "- Kein älterer Kontext.",
            "",
            "## Conversation",
        ]
        for turn in turns:
            lines.extend(
                (
                    "",
                    f"### {turn.timestamp.isoformat()}",
                    "USER:",
                    _line(turn.message, 4000),
                    "",
                    "JARVIS:",
                    _line(turn.answer, 4000),
                )
            )
        path = self._path(memory.user_hash)
        temporary = path.with_suffix(".tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _summary(turns: tuple[ConversationTurn, ...]) -> str:
        if not turns:
            return ""
        last = turns[-1]
        return (
            f"- {len(turns)} ältere Gesprächszüge vorhanden.\n"
            f"- Letzte ältere Nutzeräußerung: {_line(last.message, 300)}"
        )

    def _maintenance_sync(self) -> None:
        try:
            self.users_dir.mkdir(parents=True, exist_ok=True)
            files = list(self.users_dir.glob("*.md"))
            removed = 0
            if self.retention_days > 0:
                cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
                for path in files:
                    modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                    if modified < cutoff:
                        path.unlink()
                        removed += 1
            self.persistent_users = len(files) - removed
            if removed:
                logger.info("memory cleanup removed %d expired entries", removed)
        except OSError:
            self.persistent_ok = False
            logger.exception("memory maintenance failed")

    @staticmethod
    def _remove_file(path: Path) -> bool:
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False

    def _remove_all_sync(self) -> int:
        if not self.users_dir.exists():
            return 0
        removed = 0
        for path in self.users_dir.glob("*.md"):
            path.unlink()
            removed += 1
        return removed
