package com.jarvis.minecraft;

import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class JarvisMinecraftClient implements ClientModInitializer {
    static final Logger LOGGER = LoggerFactory.getLogger("jarvis-minecraft-bridge");

    private JarvisConfig config;
    private MinecraftApiClient apiClient;
    private final UpdateInterval updateInterval = new UpdateInterval();
    private final AtomicBoolean requestInFlight = new AtomicBoolean();
    private final AtomicLong sequence = new AtomicLong(System.currentTimeMillis());
    private boolean warnedAboutToken;
    private boolean warnedAboutSession;

    @Override
    public void onInitializeClient() {
        config = JarvisConfig.load();
        apiClient = new MinecraftApiClient(System.getenv("MINECRAFT_API_TOKEN"));
        ClientTickEvents.END_CLIENT_TICK.register(client -> {
            boolean connected = client.getConnection() != null;
            if (!GameAvailability.canSend(config.enabled, client.player != null, client.level != null, connected)) return;
            if (!apiClient.isConfigured()) {
                if (!warnedAboutToken) LOGGER.warn("Minecraft bridge is enabled but MINECRAFT_API_TOKEN is not set in the Minecraft process environment.");
                warnedAboutToken = true;
                return;
            }
            try {
                UUID.fromString(config.sessionId);
            } catch (IllegalArgumentException exception) {
                if (!warnedAboutSession) LOGGER.warn("Set session_id in config/jarvis-minecraft-bridge.properties using Copy session ID in JARVIS.");
                warnedAboutSession = true;
                return;
            }
            if (!updateInterval.isDue(System.nanoTime(), config.intervalSeconds) || !requestInFlight.compareAndSet(false, true)) return;

            MinecraftState.capture(client).ifPresentOrElse(state -> apiClient.sendState(config, state, config.sourceId, sequence.incrementAndGet())
                    .whenComplete((status, error) -> {
                        requestInFlight.set(false);
                        if (error != null) {
                            LOGGER.warn("JARVIS update failed due to a connection error ({}).", error.getClass().getSimpleName());
                        } else if (status == 401) {
                            LOGGER.warn("JARVIS rejected the Minecraft bearer token (HTTP 401); check local environment configuration.");
                        } else if (status < 200 || status >= 300) {
                            LOGGER.warn("JARVIS rejected a Minecraft update (HTTP {}).", status);
                        }
                    }), () -> requestInFlight.set(false));
        });
        LOGGER.info("JARVIS Minecraft Bridge initialized; enabled={}", config.enabled);
    }
}
