from __future__ import annotations

import os
import threading
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

load_dotenv()

ROOT = Path(__file__).resolve().parent
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
SYSTEM_INSTRUCTION = """You are JARVIS, a helpful personal AI assistant with a calm, intelligent, slightly witty personality. Be clear and conversational. Be honest about uncertainty: never invent facts or pretend to know information you do not have. You do not have access to the user's computer, live internet, or Minecraft game unless information is explicitly provided in the conversation. Do not claim otherwise."""
MAX_SESSIONS = 500

app = FastAPI(title="JARVIS", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

_client: genai.Client | None = None
_sessions: OrderedDict[str, tuple[object, threading.Lock]] = OrderedDict()
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


def _get_chat(session_id: str):
    with _sessions_lock:
        entry = _sessions.get(session_id)
        if entry is not None:
            _sessions.move_to_end(session_id)
            return entry
        chat = _get_client().chats.create(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.7,
            ),
        )
        entry = (chat, threading.Lock())
        _sessions[session_id] = entry
        while len(_sessions) > MAX_SESSIONS:
            _sessions.popitem(last=False)
        return entry


@app.get("/")
def home() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY", "").strip()),
        "model": MODEL_NAME,
    }


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict[str, str]:
    session_id = _validate_session_id(request.session_id)
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Please enter a message.")

    try:
        chat_session, session_lock = _get_chat(session_id)
        with session_lock:
            response = chat_session.send_message(message)
        answer = (response.text or "").strip()
        if not answer:
            raise HTTPException(
                status_code=502,
                detail="Gemini returned an empty response. Please try asking another way.",
            )
        return {"response": answer}
    except HTTPException:
        raise
    except Exception as exc:
        # Do not expose provider details, request data, or credentials to the browser.
        raise HTTPException(
            status_code=502,
            detail="I couldn't reach Gemini just now. Check your connection and API key, then try again.",
        ) from exc


@app.post("/api/clear")
def clear_session(request: SessionRequest) -> dict[str, bool]:
    session_id = _validate_session_id(request.session_id)
    with _sessions_lock:
        _sessions.pop(session_id, None)
    return {"cleared": True}


@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "microphone=(self)"
    return response
