package com.mlomega.xr.reflexvision

/**
 * Callbacks from [AsrKwsService] into the host (Unity via `AndroidJavaProxy`, or
 * a JVM test double). Invoked on the audio worker thread; the Unity `AsrBridge`
 * marshals onto the main thread.
 */
interface AsrKwsCallbacks {

    /**
     * A streaming ASR result. [isFinal] distinguishes a partial (endpoint not yet
     * reached — subtitle renders it muted) from a final (endpoint detected). The
     * [language] is the loaded model's language ("fr"/"en"). [startMs]/[endMs] are
     * the segment timestamps (monotonic ms) for aligning the subtitle. This maps
     * straight to a SubtitleSkill partial/final UIIntent on the C# side.
     *
     * E47-A: [isCommand] is true only for a *final* segment that ended inside the
     * wake-word command window (see [AsrKwsService.openCommandWindow]). Capture
     * always continues to the PC (life memory / hot context); this flag only tells
     * the PC to *route* the segment as a command rather than plain memory. Partials
     * are always `false`.
     */
    fun onTranscript(
        text: String,
        isFinal: Boolean,
        language: String,
        startMs: Long,
        endMs: Long,
        isCommand: Boolean,
    )

    /**
     * The configured wake word was spotted. [keyword] is the matched phrase. The
     * C# WakeWordGate turns this into "start listening for a command" + StatusBar
     * feedback.
     */
    fun onWakeWord(keyword: String, timestampMs: Long)

    /** Non-fatal error surfaced for logging/telemetry. */
    fun onError(message: String)
}
