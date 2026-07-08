package com.mlomega.xr.livetransport

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream
import org.apache.commons.compress.compressors.bzip2.BZip2CompressorInputStream
import java.io.BufferedInputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * MLOmega V19 — E48-A. Device-model provisioning client (replaces the manual
 * `adb push models\device\.` of E47).
 *
 * At pairing (endpoint + session token available) this GETs the token-gated
 * `/models/device/manifest` from the PC, works out which required models are
 * MISSING from `getExternalFilesDir()/models/`, downloads each available one,
 * sha-256-verifies it against `X-Model-Sha256` / the manifest, writes it
 * atomically (`.part` temp then rename), and — for sherpa `.tar.bz2` ASR/KWS
 * archives — extracts it so the on-device layout mirrors the repo `models/device/`
 * tree (the exact tree the E47 manual push produced).
 *
 * Placement (ADR §E48-A): this lives in `livetransport`, the module that already
 * owns the PC endpoint + session token ([SessionCredentialStore], [SignalingClient],
 * [PcEndpoint]) and OkHttp. `reflexvision` has neither an HTTP client nor the token.
 *
 * Invariants: provisioning NEVER blocks session start — it runs on a background
 * coroutine and a feature whose model is still absent stays in honest degraded
 * mode (the bridges already gate on model presence), never a crash. A partial
 * download is discarded (temp file), so an interrupted run simply re-downloads the
 * file next time (resume-by-restart).
 *
 * Progress is reported through [ModelProvisioningCallbacks] with the same
 * JNI-friendly shape as [LiveTransportCallbacks] so the Unity bridge can marshal
 * it to a discreet status card.
 */
class ModelProvisioner(
    private val appContext: Context,
    private val callbacks: ModelProvisioningCallbacks,
    /** Root the phone installs models under. Defaults to `getExternalFilesDir()/models`. */
    private val modelsRoot: File = defaultModelsRoot(appContext),
    timeoutMs: Long = DEFAULT_TIMEOUT_MS,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val running = AtomicBoolean(false)
    @Volatile private var job: Job? = null

    private val http = OkHttpClient.Builder()
        .callTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        .connectTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        // The ASR archives are 300-400 MB; the byte pump has no per-read timeout,
        // but a stalled socket must still fail — a generous read timeout does that.
        .readTimeout(READ_TIMEOUT_MS, TimeUnit.MILLISECONDS)
        .writeTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        .build()

    /**
     * Kick off provisioning against [baseUrl] (e.g. `http://192.168.1.10:8710`) with
     * the session [sessionId]/[token]. Idempotent: a second call while a run is in
     * flight is ignored. Returns immediately — all work is on a background coroutine.
     */
    fun start(baseUrl: String, sessionId: String, token: String) {
        if (!running.compareAndSet(false, true)) return
        val base = baseUrl.trimEnd('/')
        job = scope.launch {
            try {
                provision(base, sessionId, token)
            } catch (t: Throwable) {
                callbacks.onProvisioningError("__manifest__", t.message ?: "provisioning failed")
            } finally {
                running.set(false)
                callbacks.onProvisioningComplete()
            }
        }
    }

    /** Cancel an in-flight run (best effort). Safe to call repeatedly. */
    fun stop() {
        job?.cancel()
        job = null
        running.set(false)
    }

    /** True while a provisioning run is in flight. */
    fun isRunning(): Boolean = running.get()

    // --- orchestration --------------------------------------------------------

    private fun provision(base: String, sessionId: String, token: String) {
        modelsRoot.mkdirs()
        val manifestJson = fetchManifest(base, sessionId, token)
        val manifest = DeviceModelManifest.parse(manifestJson)
        val missing = manifest.missing { isPresent(it) }
        callbacks.onProvisioningPlan(manifest.models.size, missing.size)
        if (missing.isEmpty()) return

        for (entry in missing) {
            if (!running.get()) return // stopped
            try {
                downloadOne(base, sessionId, token, entry)
                callbacks.onModelReady(entry.name)
            } catch (t: Throwable) {
                // One model failing must not abort the rest, and must never crash the
                // session — the feature stays degraded until a later launch retries.
                callbacks.onProvisioningError(entry.name, t.message ?: "download failed")
            }
        }
    }

    /** True when the entry's installed artefact already exists on disk. */
    private fun isPresent(entry: DeviceModelEntry): Boolean {
        val rel = entry.installedRelativePath ?: return true // nothing to fetch
        val target = File(modelsRoot, rel)
        // An archive's extracted dir must be a non-empty directory; a file must exist
        // and be non-empty. (A zero-length file is a stale partial and re-downloads.)
        return if (entry.isArchive) {
            target.isDirectory && (target.list()?.isNotEmpty() == true)
        } else {
            target.isFile && target.length() > 0L
        }
    }

    private fun downloadOne(base: String, sessionId: String, token: String, entry: DeviceModelEntry) {
        val url = "$base${entry.endpoint}?session_id=${enc(sessionId)}&token=${enc(token)}"
        val request = Request.Builder().url(url).get().build()
        http.newCall(request).execute().use { resp ->
            if (!resp.isSuccessful) {
                throw IOException("provisioning ${resp.code} for ${entry.name}")
            }
            val body = resp.body ?: throw IOException("empty body for ${entry.name}")
            val expectedSha = (resp.header("X-Model-Sha256") ?: entry.sha256)?.lowercase()
            val total = body.contentLength()
            // Download to a sibling temp, hashing as we go, then verify before it is
            // ever exposed under its real name / extracted.
            val tmp = File(modelsRoot, tempName(entry))
            tmp.parentFile?.mkdirs()
            val actualSha = body.byteStream().use { input ->
                copyHashing(input, tmp, total) { received ->
                    callbacks.onModelProgress(entry.name, received, total)
                }
            }
            if (expectedSha != null && expectedSha.isNotEmpty() && actualSha != expectedSha) {
                tmp.delete()
                throw IOException(
                    "sha256 mismatch for ${entry.name} (expected $expectedSha got $actualSha)",
                )
            }
            installVerified(tmp, entry)
        }
    }

    /**
     * Land a verified temp file: a plain `.task` is atomically renamed into place;
     * an archive is extracted into [modelsRoot] (reproducing the repo layout) and
     * the temp archive is deleted (only the extracted tree is kept, matching the PC).
     */
    private fun installVerified(tmp: File, entry: DeviceModelEntry) {
        if (entry.isArchive) {
            extractTarBz2(tmp, modelsRoot)
            tmp.delete()
            // sherpa archives ship epoch-named onnx (encoder-epoch-99-…onnx); the
            // on-device AsrKwsService loads the canonical encoder/decoder/joiner.onnx.
            // Bridge the names so downloaded models are actually loadable (E48-A).
            entry.installedRelativePath?.let { rel ->
                normalizeSherpaDir(File(modelsRoot, rel))
            }
        } else {
            // E48-A: honour targetSubdir so the OPUS-MT translation files (encoder /
            // decoder / tokenizer) land together in one per-direction dir, mirroring
            // the repo models/device/opus-mt-*/ layout. Pre-E48-A entries have no
            // subdir → flat placement directly under modelsRoot (unchanged).
            val rel = entry.installedRelativePath ?: (entry.filename ?: entry.name)
            val target = File(modelsRoot, rel)
            atomicRename(tmp, target)
        }
    }

    private fun fetchManifest(base: String, sessionId: String, token: String): String {
        val url = "$base/models/device/manifest?session_id=${enc(sessionId)}&token=${enc(token)}"
        val request = Request.Builder().url(url).get().build()
        http.newCall(request).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw IOException("manifest ${resp.code}: ${text.take(200)}")
            return text
        }
    }

    private fun tempName(entry: DeviceModelEntry): String {
        val fn = entry.filename ?: (entry.name + if (entry.isArchive) ".tar.bz2" else "")
        // E48-A: prefix the entry name so two entries sharing a basename (the FR->EN
        // and EN->FR encoders are both `encoder_model_int8.onnx`) get distinct temp
        // files under the flat models root and never clobber each other mid-download.
        return "${entry.name}.$fn.part"
    }

    companion object {
        const val DEFAULT_TIMEOUT_MS = 30_000L
        private const val READ_TIMEOUT_MS = 120_000L
        private const val COPY_BUFFER = 1 shl 16

        /** `getExternalFilesDir(null)/models`, falling back to `getFilesDir()/models`. */
        fun defaultModelsRoot(context: Context): File {
            val ext = context.getExternalFilesDir(null)
            val base = ext ?: context.filesDir
            return File(base, "models")
        }

        private fun enc(s: String): String =
            java.net.URLEncoder.encode(s, Charsets.UTF_8.name())

        /**
         * Copy [input] into [dest], returning the lowercase hex sha256 of the bytes
         * written. [progress] is invoked with the running byte count. Pure I/O +
         * hashing (no Android): exercised on the JVM by [ModelProvisionerCoreTest].
         */
        fun copyHashing(
            input: InputStream,
            dest: File,
            total: Long,
            progress: (Long) -> Unit,
        ): String {
            val digest = MessageDigest.getInstance("SHA-256")
            dest.outputStream().use { out ->
                val buf = ByteArray(COPY_BUFFER)
                var received = 0L
                var lastReported = -1L
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    out.write(buf, 0, n)
                    digest.update(buf, 0, n)
                    received += n
                    // Throttle callbacks to ~1 % steps (or every read for small files).
                    if (total <= 0 || received - lastReported >= (total / 100).coerceAtLeast(1)) {
                        lastReported = received
                        progress(received)
                    }
                }
                progress(received)
            }
            return digest.joinToHex()
        }

        /** sha256 of an existing file (lowercase hex). */
        fun sha256Of(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buf = ByteArray(COPY_BUFFER)
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    digest.update(buf, 0, n)
                }
            }
            return digest.joinToHex()
        }

        /**
         * Atomically move [tmp] onto [target] (rename; falls back to copy+delete if
         * the rename fails, e.g. across filesystems). Any stale target is removed
         * first so the rename cannot fail on an existing file.
         */
        fun atomicRename(tmp: File, target: File) {
            target.parentFile?.mkdirs()
            if (target.exists()) target.delete()
            if (tmp.renameTo(target)) return
            // Cross-device or locked: copy then delete the temp.
            tmp.copyTo(target, overwrite = true)
            tmp.delete()
        }

        /**
         * Extract a `.tar.bz2` archive into [destDir], reproducing the archive's own
         * top-level directory (the sherpa archives ship one dir named after the
         * archive stem — the same tree `fetch_models_v19.py` extracts on the PC).
         * Pure JVM (commons-compress) so it is testable without a device.
         *
         * Zip-slip guarded: an entry escaping [destDir] is rejected.
         */
        fun extractTarBz2(archive: File, destDir: File) {
            destDir.mkdirs()
            val canonicalDest = destDir.canonicalFile
            BufferedInputStream(archive.inputStream()).use { fileIn ->
                BZip2CompressorInputStream(fileIn).use { bz ->
                    TarArchiveInputStream(bz).use { tar ->
                        var e = tar.nextTarEntry
                        while (e != null) {
                            val out = File(destDir, e.name)
                            if (!out.canonicalFile.toPath().startsWith(canonicalDest.toPath())) {
                                throw IOException("archive entry escapes target: ${e.name}")
                            }
                            if (e.isDirectory) {
                                out.mkdirs()
                            } else {
                                out.parentFile?.mkdirs()
                                out.outputStream().use { os -> tar.copyTo(os) }
                            }
                            e = tar.nextTarEntry
                        }
                    }
                }
            }
        }

        /**
         * Give a sherpa model dir the canonical `encoder.onnx` / `decoder.onnx` /
         * `joiner.onnx` names [AsrKwsService] loads. The upstream archives ship
         * epoch-tagged files (`encoder-epoch-99-avg-1-…onnx`), so this copies the
         * float (non-int8) variant of each to its canonical name when that name does
         * not already exist. Idempotent and best-effort — a dir already normalised, or
         * one whose naming does not match, is left untouched.
         */
        fun normalizeSherpaDir(dir: File) {
            if (!dir.isDirectory) return
            val files = dir.listFiles()?.filter { it.isFile } ?: return
            for (role in arrayOf("encoder", "decoder", "joiner")) {
                val canonical = File(dir, "$role.onnx")
                if (canonical.exists()) continue
                val match = files
                    .filter {
                        val n = it.name
                        n.startsWith("$role") && n.endsWith(".onnx") && !n.contains(".int8.")
                    }
                    .minByOrNull { it.name.length } // shortest = the plain float export
                    ?: continue
                try {
                    match.copyTo(canonical, overwrite = false)
                } catch (_: Exception) {
                    // leave the dir as-is; loading will surface an honest error later.
                }
            }
        }

        private fun MessageDigest.joinToHex(): String {
            val bytes = digest()
            val sb = StringBuilder(bytes.size * 2)
            for (b in bytes) {
                val v = b.toInt() and 0xFF
                sb.append(HEX[v ushr 4]); sb.append(HEX[v and 0x0F])
            }
            return sb.toString()
        }

        private val HEX = "0123456789abcdef".toCharArray()
    }
}
