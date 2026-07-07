package com.mlomega.xr.reflexvision

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Device-free tests of the E47-A wake-word command window timing. Time is driven
 * deterministically (ms values passed in) so there is no sleep/flakiness.
 */
class CommandWindowTest {

    @Test
    fun `closed window flags nothing as command`() {
        val w = CommandWindow(windowMs = 6_000L)
        assertFalse(w.isOpenAt(0L))
        assertFalse(w.isOpenAt(1_000_000L))
    }

    @Test
    fun `final inside the window is a command`() {
        val w = CommandWindow(windowMs = 6_000L)
        w.open(nowMs = 10_000L) // open until 16_000
        assertTrue(w.isOpenAt(10_500L))  // just after the wake word
        assertTrue(w.isOpenAt(16_000L))  // exactly at the deadline
    }

    @Test
    fun `final after the window closes is not a command`() {
        val w = CommandWindow(windowMs = 6_000L)
        w.open(nowMs = 10_000L) // open until 16_000
        assertFalse(w.isOpenAt(16_001L))
        assertFalse(w.isOpenAt(30_000L))
    }

    @Test
    fun `a second wake word re-extends the window`() {
        val w = CommandWindow(windowMs = 6_000L)
        w.open(nowMs = 10_000L)          // until 16_000
        assertFalse(w.isOpenAt(20_000L)) // would be closed
        w.open(nowMs = 18_000L)          // re-arm until 24_000
        assertTrue(w.isOpenAt(20_000L))  // now inside
        assertTrue(w.isOpenAt(24_000L))
        assertFalse(w.isOpenAt(24_001L))
    }

    @Test
    fun `close ends the window early`() {
        val w = CommandWindow(windowMs = 6_000L)
        w.open(nowMs = 10_000L)
        assertTrue(w.isOpenAt(11_000L))
        w.close() // e.g. command captured — re-arm the spotter, stop tagging
        assertFalse(w.isOpenAt(11_000L))
    }

    @Test
    fun `window length honors the configured duration`() {
        val short = CommandWindow(windowMs = 1_000L)
        short.open(nowMs = 0L)
        assertTrue(short.isOpenAt(1_000L))
        assertFalse(short.isOpenAt(1_001L))

        val long = CommandWindow(windowMs = 10_000L)
        long.open(nowMs = 0L)
        assertTrue(long.isOpenAt(10_000L))
    }
}
