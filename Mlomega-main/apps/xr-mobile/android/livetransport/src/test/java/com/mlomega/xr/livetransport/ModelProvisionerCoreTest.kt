package com.mlomega.xr.livetransport

import org.apache.commons.compress.archivers.tar.TarArchiveEntry
import org.apache.commons.compress.archivers.tar.TarArchiveOutputStream
import org.apache.commons.compress.compressors.bzip2.BZip2CompressorOutputStream
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.MessageDigest

/**
 * Pure-JVM tests for [ModelProvisioner]'s device-independent core (E48-A): sha256
 * over the byte pump, atomic write (`.part` → rename), tar.bz2 extraction into the
 * repo-shaped layout, and resume (a partial temp is discarded / re-downloaded).
 * No Android, no network. Mirrors the fetch_models_v19.py bz2+tar behaviour.
 */
class ModelProvisionerCoreTest {

    @get:Rule
    val tmp = TemporaryFolder()

    private fun hexSha256(bytes: ByteArray): String {
        val d = MessageDigest.getInstance("SHA-256").digest(bytes)
        return d.joinToString("") { "%02x".format(it) }
    }

    @Test
    fun `copyHashing writes the bytes and returns their sha256`() {
        val payload = ByteArray(300_000) { (it % 251).toByte() }
        val dest = File(tmp.root, "model.part")
        var lastReported = 0L
        val sha = ModelProvisioner.copyHashing(
            ByteArrayInputStream(payload), dest, payload.size.toLong(),
        ) { received -> lastReported = received }

        assertArrayEquals(payload, dest.readBytes())
        assertEquals(hexSha256(payload), sha)
        assertEquals(payload.size.toLong(), lastReported) // final progress = total
    }

    @Test
    fun `sha256Of matches copyHashing for the same bytes`() {
        val payload = "hello mlomega".toByteArray()
        val dest = File(tmp.root, "f.bin")
        val shaCopy = ModelProvisioner.copyHashing(
            ByteArrayInputStream(payload), dest, payload.size.toLong(),
        ) {}
        assertEquals(shaCopy, ModelProvisioner.sha256Of(dest))
        assertEquals(hexSha256(payload), ModelProvisioner.sha256Of(dest))
    }

    @Test
    fun `atomicRename lands the temp under the real name`() {
        val tmpFile = File(tmp.root, "gesture_recognizer.task.part")
        tmpFile.writeBytes(byteArrayOf(1, 2, 3))
        val target = File(tmp.root, "gesture_recognizer.task")

        ModelProvisioner.atomicRename(tmpFile, target)

        assertFalse("temp is gone after rename", tmpFile.exists())
        assertTrue(target.isFile)
        assertArrayEquals(byteArrayOf(1, 2, 3), target.readBytes())
    }

    @Test
    fun `atomicRename overwrites a stale target`() {
        val target = File(tmp.root, "m.task")
        target.writeBytes(byteArrayOf(9, 9, 9)) // stale
        val fresh = File(tmp.root, "m.task.part")
        fresh.writeBytes(byteArrayOf(4, 5))

        ModelProvisioner.atomicRename(fresh, target)
        assertArrayEquals(byteArrayOf(4, 5), target.readBytes())
    }

    @Test
    fun `extractTarBz2 reproduces the archive top-level dir and files`() {
        // Build a sherpa-shaped archive: one top dir with encoder/decoder/tokens.
        val archive = File(tmp.root, "sherpa-onnx-streaming-zipformer-en-2023-06-26.tar.bz2")
        writeTarBz2(
            archive,
            mapOf(
                "sherpa-onnx-streaming-zipformer-en-2023-06-26/encoder.onnx" to "ENC".toByteArray(),
                "sherpa-onnx-streaming-zipformer-en-2023-06-26/decoder.onnx" to "DEC".toByteArray(),
                "sherpa-onnx-streaming-zipformer-en-2023-06-26/tokens.txt" to "a\nb\n".toByteArray(),
            ),
        )
        val dest = tmp.newFolder("models")

        ModelProvisioner.extractTarBz2(archive, dest)

        val modelDir = File(dest, "sherpa-onnx-streaming-zipformer-en-2023-06-26")
        assertTrue(modelDir.isDirectory)
        assertArrayEquals("ENC".toByteArray(), File(modelDir, "encoder.onnx").readBytes())
        assertArrayEquals("DEC".toByteArray(), File(modelDir, "decoder.onnx").readBytes())
        assertEquals("a\nb\n", File(modelDir, "tokens.txt").readText())
    }

    @Test
    fun `extractTarBz2 rejects a zip-slip entry escaping the target`() {
        val archive = File(tmp.root, "evil.tar.bz2")
        writeTarBz2(archive, mapOf("../escape.txt" to "x".toByteArray()))
        val dest = tmp.newFolder("safe")
        var threw = false
        try {
            ModelProvisioner.extractTarBz2(archive, dest)
        } catch (e: Exception) {
            threw = true
        }
        assertTrue("zip-slip entry must be rejected", threw)
        assertFalse(File(dest.parentFile, "escape.txt").exists())
    }

    @Test
    fun `resume - a leftover partial temp is overwritten by a fresh download`() {
        // Simulate an interrupted run: a stale .part exists with wrong content.
        val stale = File(tmp.root, "gesture_recognizer.task.part")
        stale.writeBytes(ByteArray(10) { 7 })

        // A fresh copyHashing to the same temp fully replaces it (truncating write).
        val fresh = "REAL-MODEL-BYTES".toByteArray()
        val sha = ModelProvisioner.copyHashing(
            ByteArrayInputStream(fresh), stale, fresh.size.toLong(),
        ) {}

        assertArrayEquals(fresh, stale.readBytes())
        assertEquals(hexSha256(fresh), sha)
    }

    // --- helpers --------------------------------------------------------------

    /** Write a real .tar.bz2 so extraction is exercised end-to-end (no device). */
    private fun writeTarBz2(dest: File, entries: Map<String, ByteArray>) {
        val tarBytes = ByteArrayOutputStream().use { raw ->
            TarArchiveOutputStream(raw).use { tar ->
                tar.setLongFileMode(TarArchiveOutputStream.LONGFILE_POSIX)
                for ((name, bytes) in entries) {
                    val e = TarArchiveEntry(name)
                    e.size = bytes.size.toLong()
                    tar.putArchiveEntry(e)
                    tar.write(bytes)
                    tar.closeArchiveEntry()
                }
            }
            raw.toByteArray()
        }
        dest.outputStream().use { fileOut ->
            BZip2CompressorOutputStream(fileOut).use { bz ->
                bz.write(tarBytes)
            }
        }
    }
}
