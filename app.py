from __future__ import annotations

import os
import logging
import threading
import time
from collections import OrderedDict
from pathlib import Path
from uuid import UUID

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from integrations.minecraft import minecraft_prompt_context, minecraft_state_store
from integrations.minecraft_api import development_test_mode_enabled, router as minecraft_router
from integrations.minecraft_vision import configure_vision_client_provider, router as minecraft_vision_router, vision_enabled

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

DEFAULT_MODEL_NAME = "gemini-3.8-flash"
MODEL_NAME = os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL_NAME
SYSTEM_INSTRUCTION = "You are JARVIS, a helpful, calm, conversational assistant with subtle wit. Be accurate and state uncertainty. Do not claim access to the user's computer, live internet, or Minecraft unless provided in the conversation."
MAX_SESSIONS = 500
MAX_HISTORY_MESSAGES = 16
MAX_HISTORY_CHARS = 12000
logger = logging.getLogger("jarvis")

app = FastAPI(title="JARVIS", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.include_router(minecraft_router)
app.include_router(minecraft_vision_router)

_client: genai.Client | None = None
_sessions: OrderedDict[str, tuple[list[types.Content], threading.Lock]] = OrderedDict()
_sessions_lock = threading.Lock()


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=36, max_length=36)
    message: str = Field(min_length=1, max_length=8000)


class SessionRequest(BaseModel):
    session_id: str = Field(min_length=36, max_length=36)


def _validate_session_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid session identifier.") from exc


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="Gemini is not configured. Add GEMINI_API_KEY to your .env file and restart JARVIS.",
            )
        _client = genai.Client(api_key=api_key)
    return _client


configure_vision_client_provider(_get_client)


def _get_session(session_id: str) -> tuple[list[types.Content], threading.Lock]:
    with _sessions_lock:
        entry = _sessions.get(session_id)
        if entry is not None:
            _sessions.move_to_end(session_id)
            return entry
        entry = ([], threading.Lock())
        _sessions[session_id] = entry
        while len(_sessions) > MAX_SESSIONS:
            _sessions.popitem(last=False)
        return entry


def _history_size(history: list[types.Content]) -> int:
    return sum(len(part.text or "") for content in history for part in content.parts or [])


def _trim_history(history: list[types.Content]) -> None:
    while len(history) > MAX_HISTORY_MESSAGES or (
        len(history) > 2 and _history_size(history) > MAX_HISTORY_CHARS
    ):
        if len(history) >= 2:
            del history[:2]
        else:
            history.pop(0)


def _message(role: str, text: str) -> types.Content:
    return types.Content(role=role, parts=[types.Part.from_text(text=text)])


@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "model": MODEL_NAME,
        "minecraft_dev_test_mode": development_test_mode_enabled(),
        "minecraft_vision_enabled": vision_enabled(),
    }


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, str]:
    request_started = time.perf_counter()
    api_elapsed_ms: float | None = None
    session_id = _validate_session_id(request.session_id)
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Please enter a message.")

    try:
        history, session_lock = _get_session(session_id)
        with session_lock:
            contents = [*history, _message("user", message)]
            _trim_history(contents)
            client = _get_client()
            minecraft_context = minecraft_prompt_context(session_id)
            system_instruction = SYSTEM_INSTRUCTION
            if minecraft_context:
                system_instruction = f"{SYSTEM_INSTRUCTION}\n\n{minecraft_context}"
            api_started = time.perf_counter()
            try:
                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.7,
                    ),
                )
            finally:
                api_elapsed_ms = (time.perf_counter() - api_started) * 1000
            answer = (response.text or "").strip()
            if not answer:
                raise HTTPException(
                    status_code=502,
                    detail="Gemini returned an empty response. Please try asking another way.",
                )
            history[:] = contents
            history.append(_message("model", answer))
            _trim_history(history)
        return {"response": answer}
    except HTTPException:
        raise
    except Exception as exc:
        # Do not expose provider details, request data, or credentials to the browser.
        raise HTTPException(
            status_code=502,
            detail="I couldn't reach Gemini just now. Check your connection and API key, then try again.",
        ) from exc
    finally:
        total_elapsed_ms = (time.perf_counter() - request_started) * 1000
        api_time = "n/a" if api_elapsed_ms is None else f"{api_elapsed_ms:.1f}"
        logger.info("chat timing api_ms=%s total_ms=%.1f", api_time, total_elapsed_ms)


@app.post("/api/clear")
def clear_session(request: SessionRequest) -> dict[str, bool]:
    session_id = _validate_session_id(request.session_id)
    with _sessions_lock:
        _sessions.pop(session_id, None)
    minecraft_state_store.clear(session_id)
    return {"cleared": True}


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "microphone=(self)"
    return response
