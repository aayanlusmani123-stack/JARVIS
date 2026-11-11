package com.jarvis.minecraft;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Properties;
import java.util.UUID;

import net.fabricmc.loader.api.FabricLoader;

final class JarvisConfig {
    static final String DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
    static final int DEFAULT_INTERVAL_SECONDS = 5;
    static final int MIN_INTERVAL_SECONDS = 2;
    static final int MAX_INTERVAL_SECONDS = 60;

    final boolean enabled;
    final String backendUrl;
    final int intervalSeconds;
    final String sessionId;
    final String sourceId;

    private JarvisConfig(boolean enabled, String backendUrl, int intervalSeconds, String sessionId, String sourceId) {
        this.enabled = enabled;
        this.backendUrl = backendUrl;
        this.intervalSeconds = intervalSeconds;
        this.sessionId = sessionId;
        this.sourceId = sourceId;
    }

    static JarvisConfig load() {
        Path configPath = FabricLoader.getInstance().getConfigDir().resolve("jarvis-minecraft-bridge.properties");
        Properties properties = new Properties();
        try {
            if (Files.exists(configPath)) {
                try (InputStream input = Files.newInputStream(configPath)) {
                    properties.load(input);
                }
            } else {
                Files.createDirectories(configPath.getParent());
                properties.putAll(defaultProperties());
                try (OutputStream output = Files.newOutputStream(configPath)) {
                    properties.store(output, "JARVIS Minecraft Bridge settings; token is read from MINECRAFT_API_TOKEN environment variable");
                }
            }
            String sourceId = properties.getProperty("source_id", "").trim();
            try {
                UUID.fromString(sourceId);
            } catch (IllegalArgumentException exception) {
                properties.setProperty("source_id", UUID.randomUUID().toString());
                try (OutputStream output = Files.newOutputStream(configPath)) {
                    properties.store(output, "JARVIS Minecraft Bridge settings; token is read from MINECRAFT_API_TOKEN environment variable");
                }
            }
        } catch (IOException exception) {
            JarvisMinecraftClient.LOGGER.warn("Could not load or create the JARVIS mod configuration.");
        }
        return from(properties);
    }

    static JarvisConfig from(Properties properties) {
        boolean enabled = Boolean.parseBoolean(properties.getProperty("enabled", "false"));
        String backendUrl = normalizeBackendUrl(properties.getProperty("backend_url", DEFAULT_BACKEND_URL));
        int intervalSeconds = parseInterval(properties.getProperty("interval_seconds"));
        String sessionId = properties.getProperty("session_id", "").trim();
        String sourceId = properties.getProperty("source_id", "").trim();
        return new JarvisConfig(enabled, backendUrl, intervalSeconds, sessionId, sourceId);
    }

    private static Properties defaultProperties() {
        Properties properties = new Properties();
        properties.setProperty("enabled", "false");
        properties.setProperty("backend_url", DEFAULT_BACKEND_URL);
        properties.setProperty("interval_seconds", Integer.toString(DEFAULT_INTERVAL_SECONDS));
        properties.setProperty("session_id", "");
        properties.setProperty("source_id", UUID.randomUUID().toString());
        return properties;
    }

    private static String normalizeBackendUrl(String value) {
        try {
            URI uri = URI.create(value.trim()).normalize();
            String scheme = uri.getScheme();
            String host = uri.getHost();
            boolean loopback = host != null && (host.equalsIgnoreCase("localhost")
                    || host.equals("127.0.0.1") || host.equals("[::1]") || host.equals("::1"));
            if (uri.getHost() == null || uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null
                    || !("https".equalsIgnoreCase(scheme) || ("http".equalsIgnoreCase(scheme) && loopback))) {
                return DEFAULT_BACKEND_URL;
            }
            String normalized = uri.toString();
            while (normalized.endsWith("/")) normalized = normalized.substring(0, normalized.length() - 1);
            return normalized;
        } catch (IllegalArgumentException exception) {
            return DEFAULT_BACKEND_URL;
        }
    }

    private static int parseInterval(String value) {
        try {
            int parsed = Integer.parseInt(value == null ? "" : value.trim());
            return Math.max(MIN_INTERVAL_SECONDS, Math.min(MAX_INTERVAL_SECONDS, parsed));
        } catch (NumberFormatException exception) {
            return DEFAULT_INTERVAL_SECONDS;
        }
    }
}
