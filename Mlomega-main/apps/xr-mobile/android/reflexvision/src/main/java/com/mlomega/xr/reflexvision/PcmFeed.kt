package com.mlomega.xr.reflexvision

/**
 * MLOmega V19 — E47-A — external microphone feed for the on-device speech
 * pipeline.
 *
 * [AsrKwsService] no longer owns a microphone. The single audio input lives in
 * the `livetransport` module (a `JavaAudioDeviceModule` fanned out to WebRTC + a
 * PCM sink); the service consumes those same samples through this interface so
 * exactly ONE `AudioRecord` exists in the whole app (handoff §E47-A — two
 * concurrent microphones are forbidden).
 *
 * The Unity/native glue wires the transport's `PcmFeed` to
 * [AsrKwsService.asPcmSink]. This interface is defined independently here (the
 * two Android libraries do not depend on each other; they are separate `.aar`s
 * assembled by Unity) but is shape-compatible with
 * `com.mlomega.xr.livetransport.PcmFeed`.
 *
 * Threading: [onPcm] is invoked on the transport's audio thread. The service
 * copies the samples it needs and processes them on that thread (the models are
 * fast, < 100 ms), so implementations must not block for long.
 */
interface PcmFeed {

    /**
     * A microphone PCM buffer captured for the WebRTC uplink.
     *
     * @param samples 16-bit signed PCM, one sample per element; only the first
     *   [sampleCount] elements are valid and the array is reused after the call.
     * @param sampleCount number of valid samples in [samples].
     * @param sampleRate capture rate in Hz.
     * @param channels interleaved channel count (mono = 1).
     * @param timestampMs capture time in `System.currentTimeMillis()` ms.
     */
    fun onPcm(samples: ShortArray, sampleCount: Int, sampleRate: Int, channels: Int, timestampMs: Long)
}
