"""Validated state and storage boundary for a future Minecraft Fabric bridge."""

import asyncio
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class MinecraftContext:
    player_name: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    health: float | None = None
    hunger: int | None = None
    dimension: str | None = None
    biome: str | None = None
    inventory: tuple[str, ...] = ()
    equipped_items: tuple[str, ...] = ()
    screenshot_base64: str | None = None


class MinecraftContextProvider(Protocol):
    """Interface for a future adapter; no implementation is connected yet."""

    def get_context(self) -> MinecraftContext | None:
        """Return the latest game snapshot, or None when unavailable."""
        ...


class MinecraftItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    item_id: str = Field(pattern=r"^[a-z0-9_.-]+:[a-z0-9_./-]+$", max_length=128)
    count: int = Field(ge=1, le=999)
    slot: int | None = Field(default=None, ge=0, le=255)


class MinecraftGameState(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    player_username: str = Field(pattern=r"^[A-Za-z0-9_]{1,16}$")
    x: float = Field(ge=-30_000_000, le=30_000_000, allow_inf_nan=False)
    y: float = Field(ge=-2048, le=2048, allow_inf_nan=False)
    z: float = Field(ge=-30_000_000, le=30_000_000, allow_inf_nan=False)
    health: float = Field(ge=0, le=1024, allow_inf_nan=False)
    hunger: int = Field(ge=0, le=20)
    armor_points: int = Field(ge=0, le=100)
    held_item: MinecraftItem | None
    inventory: list[MinecraftItem] = Field(max_length=256)
    biome: str = Field(pattern=r"^[a-z0-9_.-]+:[a-z0-9_./-]+$", max_length=128)
    dimension: str = Field(pattern=r"^[a-z0-9_.-]+:[a-z0-9_./-]+$", max_length=128)
    game_mode: Literal["survival", "creative", "adventure", "spectator"]
    xp_level: int = Field(ge=0, le=2_147_483_647)
    time_of_day: int = Field(ge=0, le=23_999)
    alive: bool


@dataclass(frozen=True, slots=True)
class StoredMinecraftState:
    state: MinecraftGameState
    updated_at: datetime
    source_id: str | None = None
    sequence: int | None = None
    test_mode: bool = False


class MinecraftStateStore:
    MAX_SOURCES_PER_SESSION = 4
    MAX_SUBSCRIBERS_PER_SESSION = 16
    MAX_SUBSCRIBERS_TOTAL = 512

    def __init__(self, max_sessions: int = 500) -> None:
        self._states: OrderedDict[str, StoredMinecraftState] = OrderedDict()
        self._sequences: OrderedDict[str, OrderedDict[str, int]] = OrderedDict()
        self._subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, object]]]]] = {}
        self._subscriber_count = 0
        self._lock = threading.Lock()
        self._max_sessions = max_sessions

    def update(
        self,
        session_id: UUID | str,
        state: MinecraftGameState,
        updated_at: datetime | None = None,
        source_id: UUID | str | None = None,
        sequence: int | None = None,
        test_mode: bool = False,
    ) -> tuple[StoredMinecraftState | None, bool]:
        key = str(session_id)
        source_key = str(source_id) if source_id is not None else None
        record_time = updated_at or datetime.now(timezone.utc)
        with self._lock:
            source_sequences = self._sequences.get(key)
            if source_key is None and source_sequences:
                return self._states.get(key), False
            if source_key is not None and sequence is not None:
                source_sequences = self._sequences.setdefault(key, OrderedDict())
                self._sequences.move_to_end(key)
                latest_sequence = source_sequences.get(source_key)
                if latest_sequence is not None and sequence <= latest_sequence:
                    return self._states.get(key), False
                source_sequences[source_key] = sequence
                source_sequences.move_to_end(source_key)
                while len(source_sequences) > self.MAX_SOURCES_PER_SESSION:
                    source_sequences.popitem(last=False)

            record = StoredMinecraftState(state, record_time, source_key, sequence, test_mode)
            self._states[key] = record
            self._states.move_to_end(key)
            while len(self._states) > self._max_sessions:
                evicted_session, _ = self._states.popitem(last=False)
                self._sequences.pop(evicted_session, None)
            while len(self._sequences) > self._max_sessions:
                oldest_session, _ = self._sequences.popitem(last=False)
                self._states.pop(oldest_session, None)

            payload = self._payload(key, record, record_time)
            for loop, queue in self._subscribers.get(key, ()):
                try:
                    loop.call_soon_threadsafe(self._enqueue_latest, queue, payload)
                except RuntimeError:
                    pass
        return record, True

    def get(self, session_id: UUID | str) -> StoredMinecraftState | None:
        key = str(session_id)
        with self._lock:
            record = self._states.get(key)
            if record is not None:
                self._states.move_to_end(key)
            return record

    def clear(
        self,
        session_id: UUID | str,
        source_id: UUID | str | None = None,
        sequence: int | None = None,
    ) -> bool:
        key = str(session_id)
        with self._lock:
            if source_id is not None and sequence is not None:
                source_key = str(source_id)
                source_sequences = self._sequences.setdefault(key, OrderedDict())
                self._sequences.move_to_end(key)
                latest_sequence = source_sequences.get(source_key)
                if latest_sequence is not None and sequence <= latest_sequence:
                    return False
                source_sequences[source_key] = sequence
                source_sequences.move_to_end(source_key)
                while len(source_sequences) > self.MAX_SOURCES_PER_SESSION:
                    source_sequences.popitem(last=False)
            self._states.pop(key, None)
            if key in self._sequences:
                self._sequences.move_to_end(key)
            payload = self._payload(key, None, datetime.now(timezone.utc))
            for loop, queue in self._subscribers.get(key, ()):
                try:
                    loop.call_soon_threadsafe(self._enqueue_latest, queue, payload)
                except RuntimeError:
                    pass
        return True

    async def subscribe(
        self,
        session_id: UUID | str,
    ) -> asyncio.Queue[dict[str, object]]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=1)
        with self._lock:
            subscribers = self._subscribers.setdefault(str(session_id), [])
            if len(subscribers) >= self.MAX_SUBSCRIBERS_PER_SESSION or self._subscriber_count >= self.MAX_SUBSCRIBERS_TOTAL:
                if not subscribers:
                    self._subscribers.pop(str(session_id), None)
                raise RuntimeError("too many Minecraft event subscribers")
            subscribers.append((loop, queue))
            self._subscriber_count += 1
        return queue

    def unsubscribe(self, session_id: UUID | str, queue: asyncio.Queue[dict[str, object]]) -> None:
        key = str(session_id)
        with self._lock:
            subscribers = self._subscribers.get(key)
            if subscribers is None:
                return
            retained = [(loop, item) for loop, item in subscribers if item is not queue]
            self._subscriber_count -= len(subscribers) - len(retained)
            subscribers[:] = retained
            if not subscribers:
                self._subscribers.pop(key, None)

    def snapshot(self, session_id: UUID | str, now: datetime | None = None) -> dict[str, object]:
        current_time = now or datetime.now(timezone.utc)
        record = self.get(session_id)
        return self._payload(str(session_id), record, current_time)

    @staticmethod
    def _enqueue_latest(queue: asyncio.Queue[dict[str, object]], payload: dict[str, object]) -> None:
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    @staticmethod
    def _payload(
        session_id: str,
        record: StoredMinecraftState | None,
        now: datetime,
    ) -> dict[str, object]:
        if record is None:
            return {
                "session_id": session_id,
                "status": "missing",
                "available": False,
                "stale": False,
                "updated_at": None,
                "age_seconds": None,
                "state": None,
                "test_mode": False,
            }

        age_seconds = max(0.0, (now - record.updated_at).total_seconds())
        stale = age_seconds > MINECRAFT_STATE_STALE_AFTER_SECONDS
        return {
            "session_id": session_id,
            "status": "stale" if stale else "fresh",
            "available": True,
            "stale": stale,
            "updated_at": record.updated_at.isoformat(),
            "age_seconds": round(age_seconds, 1),
            "state": record.state.model_dump(mode="json"),
            "test_mode": record.test_mode,
        }


MINECRAFT_STATE_STALE_AFTER_SECONDS = 30
minecraft_state_store = MinecraftStateStore()


def minecraft_prompt_context(
    session_id: UUID | str,
    now: datetime | None = None,
) -> str | None:
    from integrations.minecraft_vision import _is_current, screenshot_analysis_store, vision_enabled

    current_time = now or datetime.now(timezone.utc)
    record = minecraft_state_store.get(session_id)
    vision = screenshot_analysis_store.get(session_id) if vision_enabled() else None
    context: list[str] = []

    if record is None:
        context.append("Fabric game state is unavailable; never invent player coordinates, health, inventory, or other game facts.")
    else:
        age_seconds = max(0.0, (current_time - record.updated_at).total_seconds())
        state_json = json.dumps(record.state.model_dump(mode="json"), separators=(",", ":"))
        test_notice = " DEVELOPMENT TEST FIXTURE, NOT REAL GAME STATE." if record.test_mode else ""
        freshness = "stale last-reported" if age_seconds > MINECRAFT_STATE_STALE_AFTER_SECONDS else "latest"
        context.append(
            f"Fabric state ({freshness}{test_notice}), updated {age_seconds:.1f} seconds ago: {state_json}. "
            "Use supplied values only; do not infer missing facts."
        )

    if vision is None:
        context.append("No screenshot analysis is available; do not claim to see current surroundings.")
    else:
        vision_current = _is_current(vision, current_time)
        capture_label = "current timestamped capture" if vision_current else "stale or unverified capture"
        test_notice = " DEVELOPMENT TEST FIXTURE, NOT REAL GAME DATA." if vision.test_mode else ""
        captured_at = vision.captured_at.isoformat() if vision.captured_at else "unknown capture time"
        context.append(
            f"Visual context ({capture_label}{test_notice}), captured at {captured_at}, analyzed at "
            f"{vision.analyzed_at.isoformat()}: {vision.analysis}. Treat unknown/old captures as historical. "
            "If visual observations conflict with timestamped Fabric state, state the discrepancy rather than silently choosing one."
        )

    return "Minecraft context: " + " ".join(context)