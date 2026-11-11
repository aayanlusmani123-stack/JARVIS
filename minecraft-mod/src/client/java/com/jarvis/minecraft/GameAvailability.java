package com.jarvis.minecraft;

final class GameAvailability {
    private GameAvailability() {}

    static boolean canSend(boolean enabled, boolean hasPlayer, boolean hasWorld, boolean connected) {
        return enabled && hasPlayer && hasWorld && connected;
    }
}
