# JARVIS Minecraft Bridge

A client-only Fabric mod for Minecraft Java Edition 26.3. It reads real state from the active local player/world and sends updates to the existing JARVIS `POST /api/minecraft/update` route. It does not create game state when the player, world, or connection is unavailable.

## Verified versions

- Minecraft: 26.3 stable; Mojang manifest lists Java 25 as required.
- Fabric Loader: 0.20.1 stable, listed by Fabric Meta for 26.3.
- Fabric API: 0.166.0+26.3, published for 26.3.
- Fabric Loom: 1.19.4 stable; artifact exists in Fabric Maven.
- Gradle wrapper: 9.8.2, matching the Fabric 26.3 example project.

## Build

Use JDK 25 and run from this directory:

```bash
./gradlew build
```

The installable mod is `build/libs/jarvis-minecraft-bridge-1.0.0.jar`. Do not install the `-sources.jar` file.

## Install and configure

1. Install Fabric Loader 0.20.1 for Minecraft 26.3 and Fabric API 0.166.0+26.3 in the game instance.
2. Copy `jarvis-minecraft-bridge-1.0.0.jar` to that instance's `mods` directory and launch the game once. The mod creates `config/jarvis-minecraft-bridge.properties` in the game config directory.
3. In JARVIS, use **Copy session ID**. Paste that existing browser session UUID into `session_id` in the mod properties. The mod does not create or guess session IDs.
4. Set `enabled=true`. `backend_url` defaults to `http://127.0.0.1:8000`; `interval_seconds` defaults to 5 and is bounded to 2 through 60. Restart Minecraft after editing these settings.
5. Make the same `MINECRAFT_API_TOKEN` available in the Minecraft launcher's process environment. The mod reads it from the environment, never from its properties file, UI, Java source, or logs. Transfer the value from the backend's `.env` to the game device through a private secret manager; do not put it in this repository or paste it into chat.

The generated config file has this shape (the session value is copied from JARVIS, not invented; `source_id` is generated once by the mod and should be left unchanged):

```properties
enabled=false
backend_url=http://127.0.0.1:8000
interval_seconds=5
session_id=
source_id=<generated UUID>
```

The config file contains no API token. Remote backend URLs must use HTTPS. Plain HTTP is allowed only for loopback URLs.

## Codespaces connection

A Minecraft client on your computer cannot directly use a Codespaces-private port through the browser's GitHub authentication. From the computer running Minecraft, install/authenticate GitHub CLI and run:

```bash
gh codespace ports forward 8000:8000 --codespace <your-codespace-name>
```

This binds the forwarded port to loopback by default and avoids making the JARVIS port public. Keep the forwarding command running, ensure JARVIS is running in Codespaces, and leave the mod's `backend_url` as `http://127.0.0.1:8000`. If local port 8000 is occupied, forward `8000:8001` and set `backend_url=http://127.0.0.1:8001`.

`POST /api/minecraft/update` and `GET /api/minecraft/state` require the bearer token. The browser SSE path uses a short-lived signed ticket minted by a same-origin request; the long-lived token is not sent to the browser. A `401` from the update endpoint means the game process token differs from the backend token; `503` means the backend has not loaded `MINECRAFT_API_TOKEN`.

## Behavior and limits

The mod sends only while enabled and the client has a player, world, and server connection. Dead players still have their real state sent with `alive=false`. Updates are asynchronous and interval-limited. Each update carries the stable `source_id` and a clock-seeded increasing sequence, allowing the backend to reject delayed old requests across ordinary game restarts. HTTP status and connection failures are logged without token values or request bodies.

The mod has been compiled and unit-tested, but has not been launched inside Minecraft in this workspace. Actual game runtime, launcher environment inheritance, local tunnel connectivity, and a real Fabric-to-JARVIS update still need manual testing.

Run the Java tests with `./gradlew test`; run the complete compile/package verification with `./gradlew clean build`.
