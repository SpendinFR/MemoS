package com.mlomega.xr.reflexvision

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * Pure-JVM tests for the E48-A [OfflineTranslator] control logic that needs no
 * ONNX Runtime native library or model weights: direction selection, on-disk
 * availability gating, honest-degraded behaviour when models are absent, and the
 * lazy-load / idle-release budget. The real int8 inference is covered by the
 * opt-in [OfflineTranslatorIntegrationTest] (skipped unless the models are on
 * disk).
 */
class OfflineTranslatorTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private fun translator(idleMs: Long = 60_000L) =
        OfflineTranslator(tmp.root, idleReleaseMs = idleMs)

    /** Lay down the three (empty is enough for the availability check) model files. */
    private fun placeModels(dir: OfflineTranslator.Direction) {
        val d = File(tmp.root, dir.subdir).apply { mkdirs() }
        File(d, OfflineTranslator.ENCODER_FILE).writeText("x")
        File(d, OfflineTranslator.DECODER_FILE).writeText("x")
        File(d, OfflineTranslator.TOKENIZER_FILE).writeText("{}")
    }

    @Test
    fun `directionFor maps fr-en and en-fr only`() {
        val t = translator()
        assertEquals(OfflineTranslator.Direction.FR_EN, t.directionFor("fr", "en"))
        assertEquals(OfflineTranslator.Direction.EN_FR, t.directionFor("en", "fr"))
        assertEquals(OfflineTranslator.Direction.FR_EN, t.directionFor("FR", "EN"))
        assertNull(t.directionFor("de", "en"))
        assertNull(t.directionFor("fr", "fr"))
        assertNull(t.directionFor(null, "en"))
    }

    @Test
    fun `shouldTranslate is true only when languages differ`() {
        val t = translator()
        assertTrue(t.shouldTranslate("fr", "en"))
        assertTrue(t.shouldTranslate("EN", "fr"))
        assertFalse(t.shouldTranslate("fr", "fr"))
        assertFalse(t.shouldTranslate("en", "EN"))
        assertFalse(t.shouldTranslate(null, "en"))
        assertFalse(t.shouldTranslate("fr", null))
    }

    @Test
    fun `isAvailable reflects the three files on disk`() {
        val t = translator()
        assertFalse(t.isAvailable(OfflineTranslator.Direction.FR_EN))
        placeModels(OfflineTranslator.Direction.FR_EN)
        assertTrue(t.isAvailable(OfflineTranslator.Direction.FR_EN))
        assertFalse(t.isAvailable(OfflineTranslator.Direction.EN_FR))
    }

    @Test
    fun `translate returns null for an unsupported pair without loading`() {
        val t = translator()
        placeModels(OfflineTranslator.Direction.FR_EN)
        assertNull(t.translate("hallo", "de", "en"))
        assertFalse(t.isLoaded())
    }

    @Test
    fun `translate returns null and never loads when models are absent`() {
        val t = translator()
        // Supported pair, but no files on disk → honest degraded, no crash.
        assertNull(t.translate("bonjour", "fr", "en"))
        assertFalse(t.isLoaded())
    }

    @Test
    fun `translate returns null on blank input`() {
        val t = translator()
        placeModels(OfflineTranslator.Direction.FR_EN)
        assertNull(t.translate("   ", "fr", "en"))
    }

    @Test
    fun `maybeReleaseIdle only releases after the idle window`() {
        // No sessions resident → nothing to release, no error.
        val t = translator(idleMs = 1_000L)
        t.maybeReleaseIdle(10_000L)
        assertFalse(t.isLoaded())
    }

    @Test
    fun `release is idempotent`() {
        val t = translator()
        t.release()
        t.release()
        assertFalse(t.isLoaded())
    }
}
