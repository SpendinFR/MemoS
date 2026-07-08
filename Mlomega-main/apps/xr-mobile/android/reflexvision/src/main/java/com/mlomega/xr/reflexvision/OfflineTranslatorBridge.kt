package com.mlomega.xr.reflexvision

import java.io.File

/**
 * MLOmega V19 — E48-A. JNI-friendly facade over [OfflineTranslator] for the Unity
 * TranslateBridge (AndroidJavaObject), mirroring the shape of the other reflex
 * bridges (AsrKwsService / GesturePipeline): a plain class with String/primitive
 * methods, no Kotlin default args or coroutines across the boundary.
 *
 * The Unity side constructs one of these with the app models root
 * (`getExternalFilesDir()/models`), then calls [translate] from a BACKGROUND
 * thread for each FINAL ASR segment while live translation is toggled on. It ticks
 * [maybeReleaseIdle] so the sessions free themselves after a minute of silence
 * (battery), and calls [release] on deactivate.
 *
 * Every method is null-safe / degraded-honest: a missing model or an inference
 * error yields null (no translation), never a crash — the subtitle then shows the
 * original line only.
 */
class OfflineTranslatorBridge(modelsRootPath: String) {

    private val translator = OfflineTranslator(File(modelsRootPath))

    /**
     * Translate one final segment [text] from [sourceLang] to [targetLang]
     * (e.g. "en" → "fr"). Returns the translation, or null when not applicable
     * (same language, unsupported pair, models absent, or any error). Blocking:
     * call off the Unity main thread.
     */
    fun translate(text: String, sourceLang: String?, targetLang: String?): String? =
        translator.translate(text, sourceLang, targetLang)

    /** True when the direction turning [sourceLang] into [targetLang] is on disk. */
    fun isAvailable(sourceLang: String?, targetLang: String?): Boolean {
        val dir = translator.directionFor(sourceLang, targetLang) ?: return false
        return translator.isAvailable(dir)
    }

    /** Release resident sessions if idle (called on a tick from the Unity side). */
    fun maybeReleaseIdle() = translator.maybeReleaseIdle()

    /** Free any resident sessions now (on deactivate). */
    fun release() = translator.release()
}
