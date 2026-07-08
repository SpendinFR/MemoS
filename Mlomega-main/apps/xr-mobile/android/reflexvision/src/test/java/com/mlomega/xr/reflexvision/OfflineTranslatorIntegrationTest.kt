package com.mlomega.xr.reflexvision

import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/**
 * Opt-in desktop integration test for the E48-A [OfflineTranslator]: it runs the
 * REAL int8 OPUS-MT encoder + merged decoder through ONNX Runtime (the
 * `onnxruntime` JVM test dep) and the pure-Kotlin [MarianTokenizer], greedy-decodes
 * one short phrase, and checks the translation.
 *
 * Skipped (JUnit assume) unless the models are on disk, so the default JVM test run
 * needs no ~108 MB download. Point it at a `models/device` tree containing
 * `opus-mt-fr-en/` via either env var:
 *   MLOMEGA_TRANSLATE_MODELS_DIR=<repo>/models/device
 *   (fetched by `python scripts/fetch_models_v19.py --device`)
 * On a machine where the repo default exists it is auto-detected. This is the
 * "translate really one phrase" check called out in the E48-A test plan.
 */
class OfflineTranslatorIntegrationTest {

    private fun modelsRoot(): File? {
        System.getenv("MLOMEGA_TRANSLATE_MODELS_DIR")?.let {
            val f = File(it)
            if (f.isDirectory) return f
        }
        // Auto-detect the repo default: this test file sits at
        // apps/xr-mobile/android/reflexvision/src/test/java/... — walk up to repo root.
        var dir: File? = File("").absoluteFile
        repeat(8) {
            val cand = dir?.let { File(it, "models/device") }
            if (cand != null && File(cand, "opus-mt-fr-en").isDirectory) return cand
            dir = dir?.parentFile
        }
        return null
    }

    @Test
    fun `fr to en translates one real phrase`() {
        val root = modelsRoot()
        assumeTrue(
            "translation models absent — run scripts/fetch_models_v19.py --device or set " +
                "MLOMEGA_TRANSLATE_MODELS_DIR",
            root != null && File(root, "opus-mt-fr-en/${OfflineTranslator.ENCODER_FILE}").isFile,
        )
        val t = OfflineTranslator(root!!)
        assertTrue(t.isAvailable(OfflineTranslator.Direction.FR_EN))
        val out = t.translate("Quelle heure est-il ?", "fr", "en")
        assertNotNull("expected a translation, got null", out)
        val lower = out!!.lowercase()
        // Greedy OPUS-MT renders this as "What time is it?"; assert the load-bearing
        // words are present rather than an exact string (quant/rounding tolerant).
        assertTrue("unexpected translation: $out", lower.contains("time"))
        assertTrue("unexpected translation: $out", lower.contains("what") || lower.contains("it"))
        t.release()
    }
}
