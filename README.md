# JARVIS — Personal AI Voice Assistant

A working, browser-based personal assistant with a Python/FastAPI backend and a responsive, dark JARVIS-inspired interface. Gemini powers the text assistant; browser speech recognition and speech synthesis provide optional voice input and output. Your Gemini key stays on the server.

> **Minecraft:** Stage 3 adds a client-only Fabric bridge for Minecraft 26.3. It sends real game state when enabled and configured; it does not fabricate data.

## Features

- Gemini chat with a helpful, slightly witty persona and per-session conversation context.
- Push-to-talk speech recognition where supported by the browser, plus a regular text-entry fallback.
- Spoken responses using the browser's installed speech voices; mute and volume controls.
- Responsive interface, animated listening/speaking indicator, microphone status, chat history, and clear-conversation control.
- API key loaded from `GEMINI_API_KEY` on the Python server; it is never sent to or embedded in frontend code.
- An authenticated Minecraft state API with session-scoped context for Minecraft questions.
- A separate Minecraft 26.3 Fabric client project under `minecraft-mod/`.
- A live Minecraft status panel delivered over Server-Sent Events, with optional voice announcements.
- An explicitly gated development simulator that is disabled by default and labels all fixture data.

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

   Set `GEMINI_API_KEY` in `.env`. Never commit this file. JARVIS defaults to `gemini-3.8-flash`, which was verified with the configured API key. You can override `GEMINI_MODEL` to another model enabled for your account.

5. Start the server:

   ```bash
   uvicorn app:app --reload --host 0.0.0.0 --port 8000
   ```

6. Open `http://localhost:8000`. In Codespaces, use the forwarded port 8000 URL. Allow microphone access for voice input; a secure browser context (localhost or HTTPS) is required. If speech recognition is unavailable or permission is denied, use the text box. Browser speech voices vary by device and operating system.

## Run in GitHub Codespaces

The devcontainer uses Python 3.12, installs `requirements.txt` when the container is created, and forwards port 8000. In the Codespaces terminal:

```bash
cp .env.example .env
code .env
```

Add your Gemini API key to `GEMINI_API_KEY` in `.env`, then start JARVIS:

```bash
python -m uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Open the forwarded port 8000 URL shown by Codespaces. The `.env` file is git-ignored; never commit API keys. Alternatively, configure `GEMINI_API_KEY` as a Codespaces secret and restart the Codespace so it is available to the app. A key is required for chat, but the interface and health endpoint can run without one. If Google reports that Gemini 2.5 Flash is unavailable to the account, set `GEMINI_MODEL` to a model available to that account and restart the server.

Conversation context is held in server memory and is cleared by the clear button or when the server restarts. Requests retain at most 8 recent exchanges and 12,000 characters of prior context. Server logs report `api_ms` for Gemini and `total_ms` for each chat request; they do not include message text or credentials.

## Usage

- Type a message and press **Send** (or Enter) for text chat.
- Press **Push to talk**, speak, and the recognized text is submitted to JARVIS. Press the button again to stop listening.
- Use the **Voice** toggle to enable/disable spoken replies and the volume slider to adjust them.
- **Clear** erases the visible chat and server-side context for this browser session.

Speech recognition and text-to-speech are browser features, not server-side audio processing. Recognition availability depends on the browser; try a current Chrome-based browser if yours does not offer the Web Speech API.

## Minecraft Context API (Stage 2)

Set `MINECRAFT_API_TOKEN` in `.env` to a long random secret before accepting Minecraft data. Keep it private and do not print or commit it. The local token is stored in the ignored `.env`; other installations must provision their own token securely.

Restart JARVIS after setting the token. `POST /api/minecraft/update` and `GET /api/minecraft/state` require `Authorization: Bearer <MINECRAFT_API_TOKEN>`. Updates use JSON with a nested `state` object. `source_id` and `sequence` are optional for older clients; the current Fabric mod supplies them to order updates:

```json
{
   "session_id": "123e4567-e89b-12d3-a456-426614174000",
   "source_id": "123e4567-e89b-12d3-a456-426614174001",
   "sequence": 1762862400000,
   "state": {
      "player_username": "Alex",
      "x": 1.5,
      "y": 64.0,
      "z": -12.25,
      "health": 18,
      "hunger": 16,
      "armor_points": 12,
      "held_item": {"item_id": "minecraft:iron_sword", "count": 1, "slot": 0},
      "inventory": [{"item_id": "minecraft:bread", "count": 3, "slot": 1}],
      "biome": "minecraft:plains",
      "dimension": "minecraft:overworld",
      "game_mode": "survival",
      "xp_level": 7,
      "time_of_day": 1000,
      "alive": true
   }
}
```

Send it to `POST /api/minecraft/update`. Read with `GET /api/minecraft/state?session_id=<JARVIS session UUID>`. Responses report `fresh`, `stale`, or `missing`; updates older than 30 seconds are stale but remain available as last-reported data. The browser's current session UUID is stored in localStorage as `jarvis-session-id`. Gemini receives the latest session snapshot on every user turn; absent or stale state is explicitly labeled so it does not invent current game details. Clearing a JARVIS conversation also clears its Minecraft state.

The live panel requests a five-minute signed ticket from same-origin `POST /api/minecraft/events-ticket`, then listens on `GET /api/minecraft/events?ticket=<short-lived-ticket>`. The long-lived API token is never sent to the browser. The SSE stream sends an initial snapshot, coalesces rapid updates to the latest value, and refreshes freshness every 15 seconds. The browser obtains a new ticket and reconnects after network errors. Optional Minecraft voice announcements are disabled by default, change-only, and suppressed while JARVIS is speaking, muted, or listening.

### Development Test Mode

Test mode is disabled by default. In the ignored local `.env`, set both flags:

```dotenv
JARVIS_ENV=development
MINECRAFT_DEV_TEST_MODE=true
```

Restart JARVIS and refresh the page. A **DEVELOPMENT TEST MODE** control appears in the Minecraft panel; select **Start simulated updates** to cycle clearly identified `JarvisTest` fixtures every three seconds, or stop to clear them. The fixtures are synthetic test data, always marked as simulated in the panel and Gemini context, and never represent real gameplay. They use separately signed, same-origin development tickets. The regular `/api/minecraft/update` route remains bearer-authenticated; development updates cannot replace or clear real state. Turn both flags off and restart to disable test mode.

Verify the mode with `curl http://localhost:8000/api/health`; it should report `"minecraft_dev_test_mode":true`. Open the dashboard, start the simulator, and confirm the amber simulated-data banner, changing fixture values, and automatic clearing when stopped. To disable it, set `MINECRAFT_DEV_TEST_MODE=false` (or `JARVIS_ENV=production`) and restart. Development routes remain unavailable unless both flags are enabled and still require an unguessable short-lived ticket signed by the configured API token.

Live game state is stored only after an authenticated Fabric client posts data. Development fixtures use a separate data path and are marked in storage, SSE, the UI, and Gemini context. The Fabric client project and its session/token setup are documented below and in `minecraft-mod/README.md`.

## Fabric Client Mod (Stage 3)

The client mod project, verified for Minecraft 26.3, is in `minecraft-mod/`. Build it with:

```bash
cd minecraft-mod
./gradlew build
```

See [minecraft-mod/README.md](minecraft-mod/README.md) for installing Fabric Loader and Fabric API, configuring the mod, securely supplying the API token, and forwarding a private Codespaces port to the Minecraft device. The client project has not been run inside Minecraft in this workspace.

## Development and checks

The project includes the FastAPI/Gemini chat, browser voice controls, and a separately built Fabric 26.3 client bridge. Run backend checks with:

```bash
python -m compileall app.py integrations
python -m pip check
python -m unittest discover -s tests -v
node --test tests/test_minecraft_frontend.js
cd minecraft-mod && ./gradlew clean build
```

A live chat requires a valid Gemini API key and network access. Minecraft answers use only recent state sent by the configured Fabric client; JARVIS does not control the PC or claim live web access.

## Project layout

```text
app.py                    FastAPI app, Gemini chat API, in-memory sessions
integrations/minecraft.py Validated Minecraft model and session state store
integrations/minecraft_api.py Authenticated Minecraft update/state routes
minecraft-mod/              Fabric 26.3 client project, config, and tests
static/index.html         Accessible app shell
static/styles.css         Responsive dark interface and waveform animation
static/app.js             Chat, microphone, recognition, and speech synthesis
.env.example              Environment variable template
requirements.txt           Python dependencies
```
