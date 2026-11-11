"""Typed boundary for a future Minecraft Fabric bridge.

This module deliberately does not connect to Minecraft. A future Fabric mod or
local companion service can translate its live game state into this snapshot,
then pass it to the assistant through an explicitly designed, authenticated API.
"""

from dataclasses import dataclass
from typing import Protocol


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
