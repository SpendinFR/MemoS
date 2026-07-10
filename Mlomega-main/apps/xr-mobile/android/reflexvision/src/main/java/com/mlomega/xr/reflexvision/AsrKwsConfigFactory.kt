package com.mlomega.xr.reflexvision

/**
 * JNI-friendly factory for [AsrKwsConfig].
 *
 * Kotlin data-class default arguments are invisible to Unity's
 * `AndroidJavaObject` JNI bridge (JNI only sees the full-arity constructor), so
 * Unity cannot construct [AsrKwsConfig] and let the defaults fill in. This
 * `@JvmStatic` entry point takes only the values Unity varies and applies the
 * config defaults for the rest — the same pattern as
 * `com.mlomega.xr.livetransport.LiveTransportConfigFactory` (ADR §E24/§E47).
 */
object AsrKwsConfigFactory {

    /**
     * Build an [AsrKwsConfig] for the E47-A single-microphone path (the service
     * consumes the transport's PCM fan-out; it does NOT own a microphone).
     *
     * @param wakeWord the user-chosen wake word (MLOmegaConfig; default "omega").
     * @param commandWindowMs how long the wake word keeps command routing armed.
     */
    @JvmStatic
    fun forUnity(
        language: AsrLanguage,
        asrModelDir: String,
        vadModelPath: String,
        kwsModelDir: String,
        wakeWord: String,
        commandWindowMs: Long,
        ownMicrophone: Boolean,
    ): AsrKwsConfig = AsrKwsConfig(
        language = language,
        asrModelDir = asrModelDir,
        vadModelPath = vadModelPath,
        kwsModelDir = kwsModelDir,
        wakeWords = listOf(wakeWord),
        ownMicrophone = ownMicrophone,
        commandWindowMs = commandWindowMs,
    )
}
