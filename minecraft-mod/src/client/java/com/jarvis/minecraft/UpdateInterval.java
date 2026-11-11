package com.jarvis.minecraft;

final class UpdateInterval {
    private long nextUpdateAtNanos;

    boolean isDue(long nowNanos, int intervalSeconds) {
        if (nowNanos < nextUpdateAtNanos) return false;
        nextUpdateAtNanos = nowNanos + intervalSeconds * 1_000_000_000L;
        return true;
    }
}
