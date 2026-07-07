package com.mlomega.xr.reflexvision

import java.util.concurrent.atomic.AtomicLong

/**
 * MLOmega V19 — E47-A — the wake-word command window.
 *
 * A wake-word hit [open]s a window of [windowMs]; a final ASR segment that ends
 * within it ([isOpenAt]) is routed as a command. The window ONLY gates routing —
 * capture never stops (all audio still flows to the PC for life memory). Pure and
 * JVM-testable: no Android or sherpa types, so the timing is covered by
 * `CommandWindowTest` without a device.
 *
 * Timestamps are `System.currentTimeMillis()`-style ms supplied by the caller, so
 * the test can drive time deterministically. Thread-safe via an atomic deadline.
 */
class CommandWindow(private val windowMs: Long) {

    /** Absolute ms deadline; 0 = closed. */
    private val untilMs = AtomicLong(0L)

    /** Open (or re-extend) the window starting at [nowMs] for [windowMs]. */
    fun open(nowMs: Long) {
        untilMs.set(nowMs + windowMs)
    }

    /** Force the window closed (e.g. once a command was captured). */
    fun close() {
        untilMs.set(0L)
    }

    /**
     * Whether a segment ending at [endMs] falls inside the open window. The end
     * timestamp is checked (not "now") so a segment that started during the window
     * still counts even if decoding finished a few ms after it lapsed.
     */
    fun isOpenAt(endMs: Long): Boolean {
        val until = untilMs.get()
        return until != 0L && endMs <= until
    }
}
