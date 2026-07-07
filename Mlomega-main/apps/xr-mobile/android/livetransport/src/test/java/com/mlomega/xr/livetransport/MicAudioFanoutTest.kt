package com.mlomega.xr.livetransport

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure-JVM tests for [MicAudioFanout] — the E47-A single-microphone fan-out.
 *
 * Proves that the on-device sherpa pipeline receives the SAME PCM WebRTC captured
 * (byte-for-byte), so there is no second microphone. Runnable with `./gradlew
 * test`: the decode is a plain byte→short transform, not a libwebrtc call.
 */
class MicAudioFanoutTest {

    private class RecordingFeed : PcmFeed {
        var lastSamples: ShortArray? = null
        var lastCount = -1
        var lastRate = -1
        var lastChannels = -1
        var lastTs = -1L
        var calls = 0
        override fun onPcm(
            samples: ShortArray,
            sampleCount: Int,
            sampleRate: Int,
            channels: Int,
            timestampMs: Long,
        ) {
            // Copy: the caller reuses the array. A real feed must do the same.
            lastSamples = samples.copyOf(sampleCount)
            lastCount = sampleCount
            lastRate = sampleRate
            lastChannels = channels
            lastTs = timestampMs
            calls++
        }
    }

    /** Little-endian PCM16 for the given samples, as WebRTC delivers it. */
    private fun pcm16le(vararg samples: Int): ByteArray {
        val out = ByteArray(samples.size * 2)
        for (i in samples.indices) {
            out[i * 2] = (samples[i] and 0xFF).toByte()
            out[i * 2 + 1] = ((samples[i] shr 8) and 0xFF).toByte()
        }
        return out
    }

    @Test
    fun `decode recovers the exact PCM16 samples including sign`() {
        val expected = shortArrayOf(0, 1, -1, 32767, -32768, 12345, -12345)
        val bytes = pcm16le(0, 1, -1, 32767, -32768, 12345, -12345)
        val decoded = MicAudioFanout.decodePcm16(bytes, expected.size)
        assertArrayEquals(expected, decoded)
    }

    @Test
    fun `fan-out delivers the same samples WebRTC captured`() {
        val fanout = MicAudioFanout()
        val feed = RecordingFeed()
        fanout.attach(feed)

        val original = shortArrayOf(100, -200, 300, -400, 500)
        val bytes = pcm16le(100, -200, 300, -400, 500)
        fanout.dispatch(bytes, bytesPerSample = 2, sampleRate = 16_000, channels = 1, timestampMs = 42L)

        assertEquals(1, feed.calls)
        assertArrayEquals(original, feed.lastSamples)
        assertEquals(5, feed.lastCount)
        assertEquals(16_000, feed.lastRate)
        assertEquals(1, feed.lastChannels)
        assertEquals(42L, feed.lastTs)
    }

    @Test
    fun `every attached feed gets the identical buffer`() {
        val fanout = MicAudioFanout()
        val a = RecordingFeed()
        val b = RecordingFeed()
        fanout.attach(a)
        fanout.attach(b)

        val bytes = pcm16le(7, 8, 9)
        fanout.dispatch(bytes, 2, 16_000, 1, 1L)

        assertArrayEquals(a.lastSamples, b.lastSamples)
        assertArrayEquals(shortArrayOf(7, 8, 9), a.lastSamples)
    }

    @Test
    fun `no feeds means no decode work and hasFeeds is false`() {
        val fanout = MicAudioFanout()
        assertFalse(fanout.hasFeeds())
        // Dispatch with no feeds must be a safe no-op.
        fanout.dispatch(pcm16le(1, 2, 3), 2, 16_000, 1, 0L)

        val feed = RecordingFeed()
        fanout.attach(feed)
        assertTrue(fanout.hasFeeds())
    }

    @Test
    fun `detached feed stops receiving`() {
        val fanout = MicAudioFanout()
        val feed = RecordingFeed()
        fanout.attach(feed)
        fanout.dispatch(pcm16le(1), 2, 16_000, 1, 0L)
        assertEquals(1, feed.calls)

        fanout.detach(feed)
        fanout.dispatch(pcm16le(2), 2, 16_000, 1, 0L)
        assertEquals(1, feed.calls) // unchanged
    }

    @Test
    fun `a throwing feed never breaks the others (capture must survive)`() {
        val fanout = MicAudioFanout()
        val bad = object : PcmFeed {
            override fun onPcm(
                samples: ShortArray,
                sampleCount: Int,
                sampleRate: Int,
                channels: Int,
                timestampMs: Long,
            ): Unit = throw RuntimeException("boom")
        }
        val good = RecordingFeed()
        fanout.attach(bad)
        fanout.attach(good)
        // Must not throw; the good feed still runs.
        fanout.dispatch(pcm16le(11, 22), 2, 16_000, 1, 0L)
        assertArrayEquals(shortArrayOf(11, 22), good.lastSamples)
    }
}
