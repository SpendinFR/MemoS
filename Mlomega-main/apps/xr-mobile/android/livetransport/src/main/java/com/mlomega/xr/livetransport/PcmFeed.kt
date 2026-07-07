package com.mlomega.xr.livetransport

/**
 * MLOmega V19 — E47-A — single-microphone audio arbitration.
 *
 * A sink for the raw microphone PCM that WebRTC captures. The transport owns
 * exactly ONE audio input (a [org.webrtc.audio.JavaAudioDeviceModule] with a
 * samples-ready callback); those *same* PCM samples are fanned out here so the
 * on-device speech pipeline (sherpa-onnx VAD + streaming ASR + KeywordSpotter in
 * the `reflexvision` module) can consume them WITHOUT opening a second
 * `AudioRecord`. Two concurrent microphones are forbidden (handoff §E47-A) — this
 * is the seam that keeps the count at one.
 *
 * Capture NEVER stops: every buffer continues to the PC over WebRTC regardless of
 * whether a feed is attached or what it does with the samples. A feed only
 * *observes* the audio; it cannot gate or drop the uplink.
 *
 * Threading: [onPcm] is invoked on the WebRTC audio-record thread (the
 * `JavaAudioDeviceModule` callback thread). Implementations must be cheap and
 * non-blocking — copy the samples and hand off to their own worker rather than
 * decoding inline. The array is owned by the caller and reused after the call
 * returns; a feed that needs to retain samples must copy them.
 */
interface PcmFeed {

    /**
     * A microphone PCM buffer that was just captured for the WebRTC uplink.
     *
     * @param samples 16-bit signed little-endian mono PCM, one sample per element.
     *   Valid range is `[0, sampleCount)`; the backing array may be longer and is
     *   reused by the caller after this call returns.
     * @param sampleCount number of valid samples in [samples].
     * @param sampleRate capture sample rate in Hz (e.g. 16000 or 48000). The feed
     *   is responsible for any resampling its models require.
     * @param channels interleaved channel count (mono = 1). The transport requests
     *   mono capture, so this is normally 1.
     * @param timestampMs capture time in `System.currentTimeMillis()` ms, for
     *   aligning downstream segments.
     */
    fun onPcm(samples: ShortArray, sampleCount: Int, sampleRate: Int, channels: Int, timestampMs: Long)
}
