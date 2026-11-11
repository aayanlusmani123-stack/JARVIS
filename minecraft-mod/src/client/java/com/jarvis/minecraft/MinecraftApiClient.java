package com.jarvis.minecraft;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.CompletableFuture;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;

final class MinecraftApiClient {
    private static final Gson GSON = new GsonBuilder().serializeNulls().create();
    private final HttpClient httpClient;
    private final String token;

    MinecraftApiClient(String token) {
        this.httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(4)).build();
        this.token = token == null ? "" : token.trim();
    }

    boolean isConfigured() {
        return !token.isEmpty();
    }

    CompletableFuture<Integer> sendState(JarvisConfig config, MinecraftState state, String sourceId, long sequence) {
        if (!isConfigured()) return CompletableFuture.failedFuture(new IllegalStateException("API token is not configured"));

        String json = GSON.toJson(Map.of(
                "session_id", config.sessionId,
                "source_id", sourceId,
                "sequence", sequence,
                "state", state));
        HttpRequest request = HttpRequest.newBuilder(updateUri(config.backendUrl))
                .timeout(Duration.ofSeconds(8))
                .header("Authorization", "Bearer " + token)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(json))
                .build();
        return httpClient.sendAsync(request, HttpResponse.BodyHandlers.discarding()).thenApply(HttpResponse::statusCode);
    }

    static URI updateUri(String backendUrl) {
        String base = backendUrl.endsWith("/") ? backendUrl.substring(0, backendUrl.length() - 1) : backendUrl;
        return URI.create(base + "/api/minecraft/update");
    }
}
