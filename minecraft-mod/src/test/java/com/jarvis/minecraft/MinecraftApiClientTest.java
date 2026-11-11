package com.jarvis.minecraft;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Properties;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CompletionException;
import java.util.concurrent.atomic.AtomicReference;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;

final class MinecraftApiClientTest {
    @Test
    void postsStageTwoPayloadAndBearerAuthorization() throws IOException {
        AtomicReference<String> requestBody = new AtomicReference<>();
        AtomicReference<String> authorization = new AtomicReference<>();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/minecraft/update", exchange -> respond(exchange, requestBody, authorization));
        server.start();
        String token = UUID.randomUUID().toString();
        MinecraftApiClient client = new MinecraftApiClient(token);
        JarvisConfig config = config("http://127.0.0.1:" + server.getAddress().getPort(), UUID.randomUUID().toString());
        MinecraftState state = sampleState();
        String sourceId = UUID.randomUUID().toString();

        try {
            int status = client.sendState(config, state, sourceId, 17).join();
            assertEquals(200, status);
            assertEquals("Bearer " + token, authorization.get());
            JsonObject payload = JsonParser.parseString(requestBody.get()).getAsJsonObject();
            assertEquals(config.sessionId, payload.get("session_id").getAsString());
            assertEquals(sourceId, payload.get("source_id").getAsString());
            assertEquals(17, payload.get("sequence").getAsLong());
            JsonObject jsonState = payload.getAsJsonObject("state");
                assertEquals(Set.of(
                    "player_username", "x", "y", "z", "health", "hunger", "armor_points", "held_item",
                    "inventory", "biome", "dimension", "game_mode", "xp_level", "time_of_day", "alive"),
                    jsonState.keySet());
            assertEquals("Alex", jsonState.get("player_username").getAsString());
            assertEquals("minecraft:plains", jsonState.get("biome").getAsString());
            assertEquals(3, jsonState.getAsJsonArray("inventory").get(0).getAsJsonObject().get("count").getAsInt());

                MinecraftState emptyHand = new MinecraftState(
                    "Alex", 1.5, 64.0, -12.25, 18.0f, 16, 12, null, List.of(),
                    "minecraft:plains", "minecraft:overworld", "survival", 7, 1000, true);
                assertEquals(200, client.sendState(config, emptyHand, sourceId, 18).join());
                JsonObject emptyHandPayload = JsonParser.parseString(requestBody.get()).getAsJsonObject();
                assertTrue(emptyHandPayload.getAsJsonObject("state").has("held_item"));
                assertTrue(emptyHandPayload.getAsJsonObject("state").get("held_item").isJsonNull());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void reportsNetworkErrorsAndMissingTokenWithoutLoggingSecrets() throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        int port = server.getAddress().getPort();
        server.stop(0);
        JarvisConfig config = config("http://127.0.0.1:" + port, UUID.randomUUID().toString());

        assertThrows(CompletionException.class, () -> new MinecraftApiClient(UUID.randomUUID().toString())
            .sendState(config, sampleState(), UUID.randomUUID().toString(), 1).join());
        assertThrows(CompletionException.class, () -> new MinecraftApiClient("")
            .sendState(config, sampleState(), UUID.randomUUID().toString(), 1).join());
    }

    @Test
    void preservesUnauthorizedHttpStatusForAuthDiagnostics() throws IOException {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/minecraft/update", exchange -> {
            try (exchange) {
                exchange.getRequestBody().readAllBytes();
                exchange.sendResponseHeaders(401, -1);
            }
        });
        server.start();
        JarvisConfig config = config("http://127.0.0.1:" + server.getAddress().getPort(), UUID.randomUUID().toString());

        try {
            assertEquals(401, new MinecraftApiClient(UUID.randomUUID().toString())
                    .sendState(config, sampleState(), UUID.randomUUID().toString(), 1).join());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void updateUriUsesConfiguredBackend() {
        assertEquals(URI.create("https://jarvis.example.test/api/minecraft/update"),
                MinecraftApiClient.updateUri("https://jarvis.example.test/"));
    }

    private static void respond(HttpExchange exchange, AtomicReference<String> body, AtomicReference<String> authorization) throws IOException {
        try (exchange) {
            body.set(new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            authorization.set(exchange.getRequestHeaders().getFirst("Authorization"));
            exchange.sendResponseHeaders(200, -1);
        }
    }

    private static JarvisConfig config(String url, String sessionId) {
        Properties properties = new Properties();
        properties.setProperty("enabled", "true");
        properties.setProperty("backend_url", url);
        properties.setProperty("session_id", sessionId);
        return JarvisConfig.from(properties);
    }

    private static MinecraftState sampleState() {
        return new MinecraftState(
                "Alex", 1.5, 64.0, -12.25, 18.0f, 16, 12,
                new MinecraftState.Item("minecraft:iron_sword", 1, null),
                List.of(new MinecraftState.Item("minecraft:bread", 3, 1)),
                "minecraft:plains", "minecraft:overworld", "survival", 7, 1000, true);
    }
}
