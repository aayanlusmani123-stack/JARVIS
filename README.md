# JARVIS — Personal AI Voice Assistant

A working, browser-based personal assistant with a Python/FastAPI backend and a responsive, dark JARVIS-inspired interface. Gemini powers the text assistant; browser speech recognition and speech synthesis provide optional voice input and output. Your Gemini key stays on the server.

> **Minecraft:** The `integrations/minecraft.py` module defines a typed future integration boundary only. There is no Fabric mod, game connection, live context, or screenshot analysis in this application yet.

## Features

- Gemini chat with a helpful, slightly witty persona and per-session conversation context.
- Push-to-talk speech recognition where supported by the browser, plus a regular text-entry fallback.
- Spoken responses using the browser's installed speech voices; mute and volume controls.
- Responsive interface, animated listening/speaking indicator, microphone status, chat history, and clear-conversation control.
- API key loaded from `GEMINI_API_KEY` on the Python server; it is never sent to or embedded in frontend code.
- A small modular Minecraft context interface reserved for a future Fabric bridge.

## Run locally

Requires Python 3.10+ and a Gemini API key.

1. Clone the repository and enter its directory.
2. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Create `.env` from the example and add your key from Google AI Studio:

   ```bash
   cp .env.example .env
   ```

   Set `GEMINI_API_KEY` in `.env`. Never commit this file. You can optionally set `GEMINI_MODEL` as well.

5. Start the server:

   ```bash
   uvicorn app:app --reload --host 0.0.0.0 --port 8000
   ```

6. Open `http://localhost:8000`. In Codespaces, use the forwarded port 8000 URL. Allow microphone access for voice input; a secure browser context (localhost or HTTPS) is required. If speech recognition is unavailable or permission is denied, use the text box. Browser speech voices vary by device and operating system.

The first message creates a Gemini conversation. The health endpoint at `/api/health` reports whether a key is configured without returning the key itself. Conversation context is held in server memory and is cleared by the clear button or when the server restarts; an older session may be evicted if the server is serving many sessions.

## Usage

- Type a message and press **Send** (or Enter) for text chat.
- Press **Push to talk**, speak, and the recognized text is submitted to JARVIS. Press the button again to stop listening.
- Use the **Voice** toggle to enable/disable spoken replies and the volume slider to adjust them.
- **Clear** erases the visible chat and server-side context for this browser session.

Speech recognition and text-to-speech are browser features, not server-side audio processing. Recognition availability depends on the browser; try a current Chrome-based browser if yours does not offer the Web Speech API.

## Development and checks

The stages are intentionally layered: (1) text chat API and Gemini session, (2) browser push-to-talk with text fallback, (3) browser speech output and controls, and (4) responsive visual polish. Run basic checks with:

```bash
python -m compileall app.py integrations
python -m pip check
```

A live chat requires a valid Gemini API key and network access. The app does not claim to control the PC or to provide live web or Minecraft information.

## Project layout

```text
app.py                    FastAPI app, Gemini chat API, in-memory sessions
integrations/minecraft.py Typed future context/provider boundary (not connected)
static/index.html         Accessible app shell
static/styles.css         Responsive dark interface and waveform animation
static/app.js             Chat, microphone, recognition, and speech synthesis
.env.example              Environment variable template
requirements.txt           Python dependencies
```
