package com.jarvis.minecraft;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

final class BridgeSchedulingTest {
    @Test
    void doesNotSendWhenDisabledOrMinecraftIsNotReady() {
        assertFalse(GameAvailability.canSend(false, true, true, true));
        assertFalse(GameAvailability.canSend(true, false, true, true));
        assertFalse(GameAvailability.canSend(true, true, false, true));
        assertFalse(GameAvailability.canSend(true, true, true, false));
        assertTrue(GameAvailability.canSend(true, true, true, true));
    }

    @Test
    void respectsConfiguredUpdateInterval() {
        UpdateInterval interval = new UpdateInterval();

        assertTrue(interval.isDue(1_000_000_000L, 5));
        assertFalse(interval.isDue(5_999_999_999L, 5));
        assertTrue(interval.isDue(6_000_000_000L, 5));
    }
}
