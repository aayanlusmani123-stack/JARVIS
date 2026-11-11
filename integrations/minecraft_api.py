"""Authenticated JSON API for future Minecraft client updates."""

import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from integrations.minecraft import (
    MINECRAFT_STATE_STALE_AFTER_SECONDS,
    MinecraftGameState,
    minecraft_state_store,
)

router = APIRouter(prefix="/api/minecraft", tags=["minecraft"])
EVENT_TICKET_TTL_SECONDS = 300


class MinecraftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    state: MinecraftGameState
    source_id: UUID | None = None
    sequence: int | None = Field(default=None, ge=0, le=9_223_372_036_854_775_807)

    @model_validator(mode="after")
    def require_ordering_fields_together(self):
        if (self.source_id is None) != (self.sequence is None):
            raise ValueError("source_id and sequence must be supplied together")
        return self


class MinecraftSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID


class MinecraftDevUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    source_id: UUID
    sequence: int = Field(ge=0, le=9_223_372_036_854_775_807)
    step: int = Field(ge=0, le=1_000_000)


class MinecraftDevClearRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    source_id: UUID
    sequence: int = Field(ge=0, le=9_223_372_036_854_775_807)


def _configured_minecraft_token() -> str:
    expected_token = os.getenv("MINECRAFT_API_TOKEN", "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=503,
            detail="Minecraft updates are not configured. Set MINECRAFT_API_TOKEN on the server.",
        )
    return expected_token


def require_minecraft_token(authorization: str | None) -> None:
    expected_token = _configured_minecraft_token()

    scheme, separator, supplied_token = (authorization or "").partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or not hmac.compare_digest(supplied_token, expected_token)
    ):
        raise HTTPException(status_code=401, detail="A valid Minecraft bearer token is required.")


@router.post("/update")
def update_minecraft_state(
    payload: MinecraftUpdateRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    require_minecraft_token(authorization)
    record, accepted = minecraft_state_store.update(
        payload.session_id,
        payload.state,
        source_id=payload.source_id,
        sequence=payload.sequence,
    )
    if not accepted:
        raise HTTPException(status_code=409, detail="Out-of-order Minecraft update was ignored.")
    if record is None:
        raise HTTPException(status_code=500, detail="Minecraft state could not be stored.")
    return {
        "accepted": True,
        "session_id": str(payload.session_id),
        "updated_at": record.updated_at.isoformat(),
        "sequence": payload.sequence,
    }


@router.get("/state")
def get_minecraft_state(
    session_id: UUID,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    require_minecraft_token(authorization)
    return minecraft_state_store.snapshot(session_id)


def _require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin", "")
    fetch_site = request.headers.get("sec-fetch-site", "")
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    request_host = forwarded_host or request.headers.get("host", "")
    if (
        fetch_site != "same-origin"
        or not origin
        or urlsplit(origin).netloc.lower() != request_host.lower()
    ):
        raise HTTPException(status_code=403, detail="Minecraft event tickets require a same-origin request.")


def development_test_mode_enabled() -> bool:
    return (
        os.getenv("JARVIS_ENV", "").strip().lower() == "development"
        and os.getenv("MINECRAFT_DEV_TEST_MODE", "").strip().lower() == "true"
    )


def _require_dev_test_mode() -> None:
    if not development_test_mode_enabled():
        raise HTTPException(status_code=404, detail="Development Minecraft test mode is disabled.")


def _issue_ticket(session_id: UUID, purpose: str) -> str:
    key = _configured_minecraft_token().encode("utf-8")
    expires_at = int(time.time()) + EVENT_TICKET_TTL_SECONDS
    nonce = secrets.token_urlsafe(16)
    session = str(session_id)
    signed_value = f"{purpose}:{session}:{expires_at}:{nonce}".encode("utf-8")
    signature = hmac.new(key, signed_value, hashlib.sha256).hexdigest()
    return f"{session}.{purpose}.{expires_at}.{nonce}.{signature}"


def _session_from_event_ticket(ticket: str, purpose: str = "events") -> UUID:
    try:
        session_part, ticket_purpose, expiry_part, nonce, signature = ticket.split(".", 4)
        session_id = UUID(session_part)
        expires_at = int(expiry_part)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid Minecraft event ticket.") from exc

    now = int(time.time())
    if ticket_purpose != purpose or expires_at < now or expires_at > now + EVENT_TICKET_TTL_SECONDS + 5:
        raise HTTPException(status_code=401, detail="Minecraft event ticket expired or has the wrong scope.")
    key = _configured_minecraft_token().encode("utf-8")
    signed_value = f"{purpose}:{session_id}:{expires_at}:{nonce}".encode("utf-8")
    expected_signature = hmac.new(key, signed_value, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=401, detail="Invalid Minecraft event ticket.")
    return session_id


@router.post("/events-ticket")
def issue_minecraft_event_ticket(payload: MinecraftSessionRequest, request: Request) -> dict[str, object]:
    _require_same_origin(request)
    return {
        "ticket": _issue_ticket(payload.session_id, "events"),
        "expires_in": EVENT_TICKET_TTL_SECONDS,
    }


DEVELOPMENT_TEST_FIXTURES = (
    {
        "player_username": "JarvisTest",
        "x": 0.0, "y": 64.0, "z": 0.0,
        "health": 20.0, "hunger": 20, "armor_points": 0,
        "held_item": None, "inventory": [],
        "biome": "minecraft:plains", "dimension": "minecraft:overworld",
        "game_mode": "survival", "xp_level": 0, "time_of_day": 1000, "alive": True,
    },
    {
        "player_username": "JarvisTest",
        "x": 8.5, "y": 64.0, "z": -3.0,
        "health": 14.0, "hunger": 16, "armor_points": 8,
        "held_item": {"item_id": "minecraft:iron_sword", "count": 1, "slot": None},
        "inventory": [{"item_id": "minecraft:bread", "count": 3, "slot": 0}],
        "biome": "minecraft:forest", "dimension": "minecraft:overworld",
        "game_mode": "survival", "xp_level": 5, "time_of_day": 6500, "alive": True,
    },
    {
        "player_username": "JarvisTest",
        "x": -21.0, "y": 72.0, "z": 11.5,
        "health": 6.0, "hunger": 8, "armor_points": 3,
        "held_item": {"item_id": "minecraft:torch", "count": 12, "slot": None},
        "inventory": [{"item_id": "minecraft:stone", "count": 24, "slot": 1}],
        "biome": "minecraft:stony_peaks", "dimension": "minecraft:overworld",
        "game_mode": "survival", "xp_level": 7, "time_of_day": 13000, "alive": True,
    },
)


@router.post("/dev-ticket")
def issue_minecraft_dev_ticket(payload: MinecraftSessionRequest, request: Request) -> dict[str, object]:
    _require_dev_test_mode()
    _require_same_origin(request)
    return {"ticket": _issue_ticket(payload.session_id, "dev"), "expires_in": EVENT_TICKET_TTL_SECONDS}


@router.post("/dev-update")
def update_minecraft_dev_state(
    payload: MinecraftDevUpdateRequest,
    x_jarvis_dev_ticket: str = Header(),
) -> dict[str, object]:
    _require_dev_test_mode()
    session_id = _session_from_event_ticket(x_jarvis_dev_ticket, "dev")
    if session_id != payload.session_id:
        raise HTTPException(status_code=401, detail="Development ticket belongs to another JARVIS session.")
    existing = minecraft_state_store.get(session_id)
    if existing is not None and not existing.test_mode:
        raise HTTPException(status_code=409, detail="Test mode cannot replace real Minecraft state.")
    state = MinecraftGameState.model_validate(DEVELOPMENT_TEST_FIXTURES[payload.step % len(DEVELOPMENT_TEST_FIXTURES)])
    record, accepted = minecraft_state_store.update(
        session_id,
        state,
        source_id=payload.source_id,
        sequence=payload.sequence,
        test_mode=True,
    )
    if not accepted:
        raise HTTPException(status_code=409, detail="Out-of-order development update was ignored.")
    if record is None:
        raise HTTPException(status_code=500, detail="Development state could not be stored.")
    return {"accepted": True, "test_mode": True, "updated_at": record.updated_at.isoformat()}


@router.post("/dev-clear")
def clear_minecraft_dev_state(
    payload: MinecraftDevClearRequest,
    x_jarvis_dev_ticket: str = Header(),
) -> dict[str, bool]:
    _require_dev_test_mode()
    session_id = _session_from_event_ticket(x_jarvis_dev_ticket, "dev")
    if session_id != payload.session_id:
        raise HTTPException(status_code=401, detail="Development ticket belongs to another JARVIS session.")
    existing = minecraft_state_store.get(session_id)
    if existing is not None and not existing.test_mode:
        raise HTTPException(status_code=409, detail="Test mode cannot clear real Minecraft state.")
    cleared = minecraft_state_store.clear(session_id, payload.source_id, payload.sequence)
    if not cleared:
        raise HTTPException(status_code=409, detail="Out-of-order development clear was ignored.")
    return {"cleared": True}


@router.get("/events")
async def minecraft_state_events(
    request: Request,
    ticket: str,
) -> StreamingResponse:
    session_id = _session_from_event_ticket(ticket, "events")
    try:
        queue = await minecraft_state_store.subscribe(session_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail="Too many Minecraft event subscribers for this session.") from exc

    async def stream():
        try:
            yield f"data: {json.dumps(minecraft_state_store.snapshot(session_id), separators=(',', ':'))}\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    payload = minecraft_state_store.snapshot(session_id)
                yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
        finally:
            minecraft_state_store.unsubscribe(session_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"},
    )
