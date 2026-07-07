package com.mlomega.xr.livetransport

import java.util.concurrent.CopyOnWriteArrayList

/**
 * MLOmega V19 — E47-A — fan-out of the single WebRTC microphone to on-device
 * consumers.
 *
 * Bridges a [org.webrtc.audio.JavaAudioDeviceModule.SamplesReadyCallback] to a
 * set of [PcmFeed]s. The `JavaAudioDeviceModule` delivers the *same* PCM buffer
 * WebRTC encodes for the uplink; this class decodes the interleaved 16-bit
 * little-endian bytes to a [ShortArray] once and dispatches it to every attached
 * feed. Nothing here can stop or mutate the uplink — the samples have already
 * been handed to libwebrtc by the time the callback fires.
 *
 * The byte→short decode ([decodePcm16]) is a pure function so the fan-out is
 * unit-testable on the JVM without any WebRTC/Android types (see
 * `MicAudioFanoutTest`).
 *
 * Threading: [dispatch] runs on the WebRTC audio-record thread. Registration
 * ([attach]/[detach]) is safe from any thread (copy-on-write list).
 */
class MicAudioFanout {

    private val feeds = CopyOnWriteArrayList<PcmFeed>()

    /** Attach a consumer of the microphone PCM. Idempotent per instance. */
    fun attach(feed: PcmFeed) {
        if (!feeds.contains(feed)) feeds.add(feed)
    }

    /** Detach a consumer; safe if it was never attached. */
    fun detach(feed: PcmFeed) {
        feeds.remove(feed)
    }

    /** Whether any consumer is currently attached (skip the decode if none). */
    fun hasFeeds(): Boolean = feeds.isNotEmpty()

    /**
     * Decode one WebRTC audio buffer and dispatch it to every attached feed.
     *
     * @param audioBytes interleaved 16-bit little-endian PCM, `bytesPerSample`==2.
     * @param bytesPerSample bytes per sample per channel (WebRTC gives 2 for PCM16).
     * @param sampleRate capture rate in Hz.
     * @param channels interleaved channel count.
     * @param timestampMs capture time (ms).
     */
    fun dispatch(
        audioBytes: ByteArray,
        bytesPerSample: Int,
        sampleRate: Int,
        channels: Int,
        timestampMs: Long,
    ) {
        if (feeds.isEmpty()) return
        val sampleCount = audioBytes.size / bytesPerSample
        val samples = decodePcm16(audioBytes, sampleCount)
        for (feed in feeds) {
            try {
                feed.onPcm(samples, sampleCount, sampleRate, channels, timestampMs)
            } catch (_: Throwable) {
                // A misbehaving feed must never break capture or the other feeds.
            }
        }
    }

    companion object {
        /**
         * Decode `sampleCount` little-endian 16-bit PCM samples from [audioBytes]
         * into a fresh [ShortArray]. Pure and JVM-testable — this is the exact
         * transform the WebRTC samples-ready callback applies, proving the fan-out
         * hands sherpa the *same* audio WebRTC sent (byte-for-byte).
         */
        @JvmStatic
        fun decodePcm16(audioBytes: ByteArray, sampleCount: Int): ShortArray {
            val out = ShortArray(sampleCount)
            var b = 0
            for (i in 0 until sampleCount) {
                val lo = audioBytes[b].toInt() and 0xFF
                val hi = audioBytes[b + 1].toInt() // sign-extended high byte
                out[i] = ((hi shl 8) or lo).toShort()
                b += 2
            }
            return out
        }
    }
}
