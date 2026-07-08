package com.mlomega.xr.livetransport

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure-JVM tests for [DeviceModelManifest] — the E48-A provisioning parse + plan
 * layer. Proves the phone parses the PC's `/models/device/manifest` correctly and
 * downloads exactly the required-but-missing, PC-available models. No Android, no
 * network (same style as [MicAudioFanoutTest]).
 */
class DeviceModelManifestTest {

    /** A manifest matching sessionhub_http.build_device_manifest_payload's shape. */
    private val sampleJson = """
        {
          "models": [
            {"name":"asr_stream_en","kind":"asr_streaming","license":"Apache-2.0",
             "format":"archive_tar_bz2",
             "filename":"sherpa-onnx-streaming-zipformer-en-2023-06-26.tar.bz2",
             "sha256":"abc123","available":true,
             "endpoint":"/models/device/asr_stream_en"},
            {"name":"kws_en","kind":"keyword_spotting","license":"Apache-2.0",
             "format":"archive_tar_bz2",
             "filename":"sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2",
             "sha256":"def456","available":true,
             "endpoint":"/models/device/kws_en"},
            {"name":"gesture_recognizer","kind":"gesture_recognizer","license":"Apache-2.0",
             "format":"file","filename":"gesture_recognizer.task",
             "sha256":"999aaa","available":true,
             "endpoint":"/models/device/gesture_recognizer"},
            {"name":"asr_stream_fr","kind":"asr_streaming","license":"Apache-2.0",
             "format":"archive_tar_bz2","filename":null,"sha256":null,
             "available":false,"endpoint":"/models/device/asr_stream_fr"}
          ],
          "count": 4
        }
    """.trimIndent()

    @Test
    fun `parse reads every entry with its fields`() {
        val m = DeviceModelManifest.parse(sampleJson)
        assertEquals(4, m.models.size)
        val en = m.models.first { it.name == "asr_stream_en" }
        assertTrue(en.isArchive)
        assertTrue(en.available)
        assertEquals("abc123", en.sha256)
        assertEquals("/models/device/asr_stream_en", en.endpoint)
        val task = m.models.first { it.name == "gesture_recognizer" }
        assertFalse(task.isArchive)
        assertEquals("gesture_recognizer.task", task.filename)
    }

    @Test
    fun `archive installed path is the extracted dir named after the archive stem`() {
        val m = DeviceModelManifest.parse(sampleJson)
        val en = m.models.first { it.name == "asr_stream_en" }
        assertEquals("sherpa-onnx-streaming-zipformer-en-2023-06-26", en.installedRelativePath)
        val task = m.models.first { it.name == "gesture_recognizer" }
        assertEquals("gesture_recognizer.task", task.installedRelativePath)
    }

    @Test
    fun `missing selects available entries not yet on disk`() {
        val m = DeviceModelManifest.parse(sampleJson)
        // Pretend only the gesture .task is already present.
        val present = setOf("gesture_recognizer")
        val missing = m.missing { it.name in present }
        assertEquals(setOf("asr_stream_en", "kws_en"), missing.map { it.name }.toSet())
    }

    @Test
    fun `unavailable entries are never selected even when absent`() {
        val m = DeviceModelManifest.parse(sampleJson)
        // Nothing on disk: the unavailable FR ASR must still be skipped.
        val missing = m.missing { false }
        assertFalse(missing.any { it.name == "asr_stream_fr" })
        assertEquals(setOf("asr_stream_en", "kws_en", "gesture_recognizer"), missing.map { it.name }.toSet())
    }

    @Test
    fun `fully provisioned phone downloads nothing`() {
        val m = DeviceModelManifest.parse(sampleJson)
        val missing = m.missing { true } // everything present
        assertTrue(missing.isEmpty())
    }

    @Test
    fun `parse tolerates an empty or malformed models array`() {
        assertTrue(DeviceModelManifest.parse("""{"count":0}""").models.isEmpty())
        assertTrue(DeviceModelManifest.parse("""{"models":[]}""").models.isEmpty())
    }

    @Test
    fun `archive suffix stripping handles tar bz2`() {
        assertEquals("foo", DeviceModelEntry.stripArchiveSuffix("foo.tar.bz2"))
        assertEquals("bar.task", DeviceModelEntry.stripArchiveSuffix("bar.task"))
    }

    // --- E48-A: multi-file translation models placed under a target_subdir --------

    /** Two directions' encoders share a basename; target_subdir keeps them apart. */
    private val translateJson = """
        {
          "models": [
            {"name":"translate_fr_en_encoder","kind":"translation","license":"Apache-2.0",
             "format":"file","filename":"encoder_model_int8.onnx","sha256":"aa",
             "available":true,"endpoint":"/models/device/translate_fr_en_encoder",
             "target_subdir":"opus-mt-fr-en"},
            {"name":"translate_fr_en_tokenizer","kind":"translation","license":"Apache-2.0",
             "format":"file","filename":"tokenizer.json","sha256":"bb",
             "available":true,"endpoint":"/models/device/translate_fr_en_tokenizer",
             "target_subdir":"opus-mt-fr-en"},
            {"name":"translate_en_fr_encoder","kind":"translation","license":"Apache-2.0",
             "format":"file","filename":"encoder_model_int8.onnx","sha256":"cc",
             "available":true,"endpoint":"/models/device/translate_en_fr_encoder",
             "target_subdir":"opus-mt-en-fr"}
          ],
          "count": 3
        }
    """.trimIndent()

    @Test
    fun `translation file installs under its target subdir`() {
        val m = DeviceModelManifest.parse(translateJson)
        val enc = m.models.first { it.name == "translate_fr_en_encoder" }
        assertEquals("opus-mt-fr-en", enc.targetSubdir)
        assertEquals("opus-mt-fr-en/encoder_model_int8.onnx", enc.installedRelativePath)
        val tok = m.models.first { it.name == "translate_fr_en_tokenizer" }
        assertEquals("opus-mt-fr-en/tokenizer.json", tok.installedRelativePath)
    }

    @Test
    fun `same-basename encoders in different directions map to distinct paths`() {
        val m = DeviceModelManifest.parse(translateJson)
        val fr = m.models.first { it.name == "translate_fr_en_encoder" }.installedRelativePath
        val en = m.models.first { it.name == "translate_en_fr_encoder" }.installedRelativePath
        assertEquals("opus-mt-fr-en/encoder_model_int8.onnx", fr)
        assertEquals("opus-mt-en-fr/encoder_model_int8.onnx", en)
        // A flat scheme would have collided; the subdir keeps them apart.
        assertFalse(fr == en)
    }

    @Test
    fun `pre-E48-A entries have no target subdir`() {
        val m = DeviceModelManifest.parse(sampleJson)
        assertEquals(null, m.models.first { it.name == "gesture_recognizer" }.targetSubdir)
        assertEquals(null, m.models.first { it.name == "asr_stream_en" }.targetSubdir)
    }
}
