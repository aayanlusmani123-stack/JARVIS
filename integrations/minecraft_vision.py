"""Ephemeral, authenticated screenshot analysis for Minecraft sessions."""

import asyncio
import hashlib
import io
import json
import os
import threading
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict

from integrations.minecraft import StoredMinecraftState, minecraft_state_store
from integrations.minecraft_api import (
    EVENT_TICKET_TTL_SECONDS,
    _issue_ticket,
    _require_same_origin,
    _session_from_event_ticket,
)

router = APIRouter(prefix="/api/minecraft", tags=["minecraft-vision"])
MAX_SCREENSHOT_BYTES = 8 * 1024 * 1024
MAX_SCREENSHOT_PIXELS = 24_000_000
MAX_IMAGE_EDGE = 1536
MAX_VISION_TEXT_CHARS = 6000
VISION_ANALYSIS_TTL_SECONDS = 30 * 60
MIN_VISION_REQUEST_INTERVAL_SECONDS = 10
SCREENSHOT_CURRENT_SECONDS = 30
GeminiClientProvider = Callable[[], object]
_client_provider: GeminiClientProvider | None = None


def configure_vision_client_provider(provider: GeminiClientProvider) -> None:
    global _client_provider
    _client_provider = provider


class VisionSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID


@dataclass(frozen=True, slots=True)
class ScreenshotAnalysis:
    session_id: str
    digest: str
    analysis: str
    captured_at: datetime | None
    received_at: datetime
    analyzed_at: datetime
    timestamp_basis: str
    mime_type: str
    width: int
    height: int
    test_mode: bool


class ScreenshotAnalysisStore:
    """Stores only expiring text and hashes; screenshot bytes are never retained."""

    def __init__(self, max_sessions: int = 500) -> None:
        self._records: OrderedDict[str, ScreenshotAnalysis] = OrderedDict()
        self._last_request_at: dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._max_sessions = max_sessions

    def reserve(self, session_id: UUID | str, digest: str, now: datetime) -> tuple[str, ScreenshotAnalysis | None, float]:
        key = str(session_id)
        with self._lock:
            record = self._records.get(key)
            if record and now - record.analyzed_at > timedelta(seconds=VISION_ANALYSIS_TTL_SECONDS):
                self._records.pop(key, None)
                record = None
            if record and record.digest == digest:
                self._records.move_to_end(key)
                return "duplicate", record, 0.0
            last_request_at = self._last_request_at.get(key)
            if last_request_at:
                remaining = MIN_VISION_REQUEST_INTERVAL_SECONDS - (now - last_request_at).total_seconds()
                if remaining > 0:
                    return "rate_limited", None, remaining
            self._last_request_at[key] = now
            return "analyze", None, 0.0

    def save(self, record: ScreenshotAnalysis) -> None:
        with self._lock:
            self._records[record.session_id] = record
            self._records.move_to_end(record.session_id)
            while len(self._records) > self._max_sessions:
                old_session, _ = self._records.popitem(last=False)
                self._last_request_at.pop(old_session, None)
            while len(self._last_request_at) > self._max_sessions:
                self._last_request_at.pop(next(iter(self._last_request_at)))

    def get(self, session_id: UUID | str) -> ScreenshotAnalysis | None:
        key = str(session_id)
        now = datetime.now(timezone.utc)
        with self._lock:
            record = self._records.get(key)
            if record and now - record.analyzed_at > timedelta(seconds=VISION_ANALYSIS_TTL_SECONDS):
                self._records.pop(key, None)
                return None
            if record:
                self._records.move_to_end(key)
            return record


screenshot_analysis_store = ScreenshotAnalysisStore()


def vision_enabled() -> bool:
    return os.getenv("MINECRAFT_VISION_ENABLED", "").strip().lower() == "true"


def _is_current(record: ScreenshotAnalysis, now: datetime) -> bool:
    return (
        record.timestamp_basis == "live-capture"
        and record.captured_at is not None
        and max(0.0, (now - record.captured_at).total_seconds()) <= SCREENSHOT_CURRENT_SECONDS
    )


def _serialize_record(record: ScreenshotAnalysis, cached: bool = False) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    age = None if record.captured_at is None else round(max(0.0, (now - record.captured_at).total_seconds()), 1)
    return {
        "analysis": record.analysis,
        "captured_at": record.captured_at.isoformat() if record.captured_at else None,
        "received_at": record.received_at.isoformat(),
        "analyzed_at": record.analyzed_at.isoformat(),
        "timestamp_basis": record.timestamp_basis,
        "capture_age_seconds": age,
        "status": "fresh" if _is_current(record, now) else "stale",
        "mime_type": record.mime_type,
        "width": record.width,
        "height": record.height,
        "cached": cached,
        "test_mode": record.test_mode,
    }


def _normalize_image(image_bytes: bytes) -> tuple[bytes, str, int, int]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image_bytes)) as source:
                if source.format not in {"PNG", "JPEG"}:
                    raise ValueError("Only PNG and JPEG screenshots are supported.")
                width, height = source.size
                if width <= 0 or height <= 0 or width * height > MAX_SCREENSHOT_PIXELS:
                    raise ValueError("Screenshot dimensions exceed the allowed limit.")
                source.verify()
            with Image.open(io.BytesIO(image_bytes)) as source:
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
                width, height = image.size
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=78, optimize=True)
                compressed = output.getvalue()
                if len(compressed) > MAX_SCREENSHOT_BYTES:
                    raise ValueError("Compressed screenshot exceeds the allowed size.")
                return compressed, "image/jpeg", width, height
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Screenshot dimensions exceed the allowed limit.") from exc
    except (OSError, SyntaxError) as exc:
        raise ValueError("Screenshot is not a valid PNG or JPEG image.") from exc


def _parse_capture_timestamp(value: str | None, basis: str) -> tuple[datetime | None, str]:
    if not value:
        return None, "unknown"
    try:
        captured_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid screenshot timestamp.") from exc
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise HTTPException(status_code=422, detail="Screenshot timestamp must include a timezone.")
    captured_at = captured_at.astimezone(timezone.utc)
    if captured_at > datetime.now(timezone.utc) + timedelta(seconds=30):
        raise HTTPException(status_code=422, detail="Screenshot timestamp is in the future.")
    if basis not in {"live-capture", "file-modified", "unknown"}:
        raise HTTPException(status_code=422, detail="Invalid screenshot timestamp basis.")
    return captured_at, basis


def _vision_prompt(
    captured_at: datetime | None,
    timestamp_basis: str,
    received_at: datetime,
    game_state: StoredMinecraftState | None,
) -> str:
    if captured_at is None:
        capture_info = "Capture time is unknown; do not describe the screenshot as current."
    else:
        age = max(0.0, (received_at - captured_at).total_seconds())
        capture_info = (
            f"Screenshot capture timestamp: {captured_at.isoformat()} ({timestamp_basis}; {age:.1f} seconds before receipt). "
            "Treat it as current only when timestamp_basis is live-capture and it is no more than 30 seconds old."
        )
    if game_state is None:
        state_info = "No Minecraft mod state snapshot is available. Do not infer coordinates, health, inventory, or game mode from the image."
    else:
        state_json = json.dumps(game_state.state.model_dump(mode="json"), separators=(",", ":"))
        state_age = max(0.0, (received_at - game_state.updated_at).total_seconds())
        label = "DEVELOPMENT TEST DATA, NOT REAL GAME STATE" if game_state.test_mode else "Fabric client state"
        state_info = f"{label}, updated {state_age:.1f} seconds before screenshot analysis: {state_json}"
    return (
        "Analyze this Minecraft screenshot conservatively. Describe visible surroundings, mobs, blocks, structures, containers, "
        "interfaces, signs, readable text, and hazards. State uncertainty for obscured or ambiguous content. Do not infer unseen inventory. "
        "Use the structured Fabric snapshot as authoritative for player coordinates, health, hunger, armor, held item, inventory, biome, "
        "dimension, mode, XP, time, and alive status. If the image conflicts with that snapshot, report the discrepancy and timestamps. "
        "Never treat an unknown or old screenshot as current.\n\n"
        f"{capture_info}\n{state_info}"
    )


def _call_gemini_vision(client: object, model: str, image_bytes: bytes, prompt: str) -> str:
    from google.genai import types

    response = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt],
        config=types.GenerateContentConfig(temperature=0.2),
    )
    analysis = (response.text or "").strip()
    if not analysis:
        raise RuntimeError("Gemini returned an empty vision response")
    return analysis[:MAX_VISION_TEXT_CHARS]


def _gemini_client() -> object:
    if _client_provider is None:
        raise HTTPException(status_code=503, detail="Gemini vision is not available in this process.")
    return _client_provider()


@router.post("/vision-ticket")
def issue_vision_ticket(payload: VisionSessionRequest, request: Request) -> dict[str, object]:
    if not vision_enabled():
        raise HTTPException(status_code=404, detail="Minecraft screen vision is disabled on this server.")
    _require_same_origin(request)
    return {"ticket": _issue_ticket(payload.session_id, "vision"), "expires_in": EVENT_TICKET_TTL_SECONDS}


@router.post("/screenshot")
async def analyze_minecraft_screenshot(
    file: UploadFile = File(...),
    captured_at: str | None = Form(default=None),
    timestamp_basis: str = Form(default="unknown"),
    x_jarvis_vision_ticket: str = Header(),
) -> dict[str, object]:
    if not vision_enabled():
        raise HTTPException(status_code=404, detail="Minecraft screen vision is disabled on this server.")
    session_id = _session_from_event_ticket(x_jarvis_vision_ticket, "vision")
    captured_timestamp, timestamp_basis = _parse_capture_timestamp(captured_at, timestamp_basis)
    if file.size is not None and file.size > MAX_SCREENSHOT_BYTES:
        await file.close()
        raise HTTPException(status_code=413, detail="Screenshot exceeds the 8 MiB upload limit.")
    raw_image = await file.read(MAX_SCREENSHOT_BYTES + 1)
    await file.close()
    if not raw_image:
        raise HTTPException(status_code=422, detail="Screenshot file is empty.")
    if len(raw_image) > MAX_SCREENSHOT_BYTES:
        raise HTTPException(status_code=413, detail="Screenshot exceeds the 8 MiB upload limit.")
    try:
        image_bytes, mime_type, width, height = await asyncio.to_thread(_normalize_image, raw_image)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    received_at = datetime.now(timezone.utc)
    digest = hashlib.sha256(image_bytes).hexdigest()
    reservation, cached_record, retry_after = screenshot_analysis_store.reserve(session_id, digest, received_at)
    if reservation == "duplicate" and cached_record is not None:
        game_state = minecraft_state_store.get(session_id)
        refreshed_record = ScreenshotAnalysis(
            session_id=str(session_id),
            digest=digest,
            analysis=cached_record.analysis,
            captured_at=captured_timestamp,
            received_at=received_at,
            analyzed_at=cached_record.analyzed_at,
            timestamp_basis=timestamp_basis,
            mime_type=mime_type,
            width=width,
            height=height,
            test_mode=bool(game_state and game_state.test_mode),
        )
        screenshot_analysis_store.save(refreshed_record)
        return _serialize_record(refreshed_record, cached=True)
    if reservation == "rate_limited":
        raise HTTPException(
            status_code=429,
            detail="Screenshot analysis is rate-limited for this session.",
            headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
        )

    game_state = minecraft_state_store.get(session_id)
    prompt = _vision_prompt(captured_timestamp, timestamp_basis, received_at, game_state)
    try:
        client = _gemini_client()
        model = os.getenv("GEMINI_MODEL", "").strip() or "gemini-3.8-flash"
        analysis = await asyncio.to_thread(_call_gemini_vision, client, model, image_bytes, prompt)
    except HTTPException:
        raise
    except Exception as exc:
        if getattr(exc, "code", None) == 429:
            raise HTTPException(
                status_code=429,
                detail="Gemini vision is rate-limited. Try again shortly.",
                headers={"Retry-After": "30"},
            ) from exc
        raise HTTPException(status_code=502, detail="Screenshot analysis failed. Try again later.") from exc

    record = ScreenshotAnalysis(
        session_id=str(session_id),
        digest=digest,
        analysis=analysis,
        captured_at=captured_timestamp,
        received_at=received_at,
        analyzed_at=datetime.now(timezone.utc),
        timestamp_basis=timestamp_basis,
        mime_type=mime_type,
        width=width,
        height=height,
        test_mode=bool(game_state and game_state.test_mode),
    )
    screenshot_analysis_store.save(record)
    return _serialize_record(record)
