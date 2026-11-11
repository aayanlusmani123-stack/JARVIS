package com.jarvis.minecraft;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Properties;

import org.junit.jupiter.api.Test;

final class JarvisConfigTest {
    @Test
    void firstRunDefaultsIncludeStableSourceId() throws IOException {
        Properties defaults = new Properties();
        defaults.setProperty("enabled", "false");
        defaults.setProperty("backend_url", JarvisConfig.DEFAULT_BACKEND_URL);
        defaults.setProperty("interval_seconds", Integer.toString(JarvisConfig.DEFAULT_INTERVAL_SECONDS));
        defaults.setProperty("session_id", "");
        defaults.setProperty("source_id", java.util.UUID.randomUUID().toString());
        Path configCopy = Files.createTempFile("jarvis-config-test", ".properties");
        try {
            try (var writer = Files.newBufferedWriter(configCopy)) {
                defaults.store(writer, "test fixture");
            }
            Properties loaded = new Properties();
            try (var reader = Files.newBufferedReader(configCopy)) {
                loaded.load(reader);
            }
            JarvisConfig config = JarvisConfig.from(loaded);
            assertFalse(config.enabled);
            assertEquals(JarvisConfig.DEFAULT_BACKEND_URL, config.backendUrl);
            assertEquals(JarvisConfig.DEFAULT_INTERVAL_SECONDS, config.intervalSeconds);
            assertTrue(config.sessionId.isEmpty());
            assertTrue(java.util.UUID.fromString(config.sourceId) != null);
        } finally {
            Files.deleteIfExists(configCopy);
        }
    }

    @Test
    void defaultsAreDisabledAndUseLocalBackend() {
        JarvisConfig config = JarvisConfig.from(new Properties());

        assertFalse(config.enabled);
        assertEquals(JarvisConfig.DEFAULT_BACKEND_URL, config.backendUrl);
        assertEquals(JarvisConfig.DEFAULT_INTERVAL_SECONDS, config.intervalSeconds);
        assertTrue(config.sessionId.isEmpty());
        assertTrue(config.sourceId.isEmpty());
    }

    @Test
    void readsBackendUrlIntervalAndEnabledFlag() {
        Properties properties = new Properties();
        properties.setProperty("enabled", "true");
        properties.setProperty("backend_url", "https://jarvis.example.test/");
        properties.setProperty("interval_seconds", "9");
        properties.setProperty("session_id", "01234567-89ab-cdef-0123-456789abcdef");
        properties.setProperty("source_id", "fedcba98-7654-3210-fedc-ba9876543210");

        JarvisConfig config = JarvisConfig.from(properties);

        assertTrue(config.enabled);
        assertEquals("https://jarvis.example.test", config.backendUrl);
        assertEquals(9, config.intervalSeconds);
        assertEquals("01234567-89ab-cdef-0123-456789abcdef", config.sessionId);
        assertEquals("fedcba98-7654-3210-fedc-ba9876543210", config.sourceId);
    }

    @Test
    void clampsIntervalsAndRejectsUnsafeUrls() {
        Properties properties = new Properties();
        properties.setProperty("backend_url", "https://user:password@example.test");
        properties.setProperty("interval_seconds", "1");

        JarvisConfig config = JarvisConfig.from(properties);

        assertEquals(JarvisConfig.DEFAULT_BACKEND_URL, config.backendUrl);
        assertEquals(JarvisConfig.MIN_INTERVAL_SECONDS, config.intervalSeconds);

        properties.setProperty("backend_url", "http://remote.example.test");
        assertEquals(JarvisConfig.DEFAULT_BACKEND_URL, JarvisConfig.from(properties).backendUrl);
    }
}
