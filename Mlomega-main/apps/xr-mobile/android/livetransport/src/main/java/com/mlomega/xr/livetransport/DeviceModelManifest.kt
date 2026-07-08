package com.mlomega.xr.livetransport

import org.json.JSONObject

/**
 * MLOmega V19 — E48-A.
 *
 * Pure parse/plan layer for the device-model provisioning client. Kept free of
 * any Android / OkHttp import so the manifest parsing and the "which models are
 * missing" selection can run on the plain JVM ([DeviceModelManifestTest]) —
 * the same test-first split the E47-A [MicAudioFanout] uses.
 *
 * The PC serves [DeviceModelManifest] at the token-gated
 * `GET /models/device/manifest` (E47-C, `sessionhub_http.build_device_manifest_payload`):
 * one entry per device-local model (offline ASR/KWS + MediaPipe gestures) with a
 * stable download endpoint, its sha256, and an `available` flag (true only when
 * the PC has already fetched the artefact). The phone downloads each MISSING and
 * available entry, sha-256-verifies it, and lands it under
 * `getExternalFilesDir()/models/` — mirroring the repo's `models/device/` layout
 * (the same tree the E47 manual `adb push models\device\.` produced).
 */

/** One model the PC advertises for the phone to provision. Mirrors the JSON. */
data class DeviceModelEntry(
    val name: String,
    val kind: String?,
    val license: String?,
    /** "file" (MediaPipe .task) or "archive_tar_bz2" (sherpa .tar.bz2). */
    val format: String,
    /** Basename of the served artefact (e.g. `gesture_recognizer.task`), or null. */
    val filename: String?,
    /** Hex sha256 the phone verifies the download against, or null when unknown. */
    val sha256: String?,
    /** Only entries the PC has actually fetched are downloadable. */
    val available: Boolean,
    /** SessionHub route, e.g. `/models/device/gesture_recognizer`. */
    val endpoint: String,
    /**
     * E48-A: subdirectory (under the app models root) a single-file entry is placed
     * in, so several files of one multi-file model (the OPUS-MT translation encoder
     * / decoder / tokenizer) land in the same directory. Null on every pre-E48-A
     * entry — those keep their flat placement directly under the models root.
     */
    val targetSubdir: String? = null,
) {
    val isArchive: Boolean get() = format == FORMAT_ARCHIVE

    /**
     * Path (relative to the app models root) that must exist for this entry to be
     * considered provisioned. For a `.task` file it is the file itself; for an
     * archive it is the extracted directory named after the archive stem (the tar
     * top-level dir matches the archive basename, e.g.
     * `sherpa-onnx-streaming-zipformer-en-2023-06-26`). A single-file entry carrying
     * a [targetSubdir] (E48-A translation files) is the file inside that subdir.
     * Null when the PC did not report a filename (nothing to verify yet).
     */
    val installedRelativePath: String?
        get() {
            val fn = filename ?: return null
            return when {
                isArchive -> stripArchiveSuffix(fn)
                targetSubdir != null -> "$targetSubdir/$fn"
                else -> fn
            }
        }

    companion object {
        const val FORMAT_ARCHIVE = "archive_tar_bz2"
        const val FORMAT_FILE = "file"

        /** `foo.tar.bz2` -> `foo`; leaves a non-archive name untouched. */
        fun stripArchiveSuffix(filename: String): String = when {
            filename.endsWith(".tar.bz2") -> filename.removeSuffix(".tar.bz2")
            filename.endsWith(".tbz2") -> filename.removeSuffix(".tbz2")
            filename.endsWith(".tar.gz") -> filename.removeSuffix(".tar.gz")
            else -> filename
        }
    }
}

/** The parsed provisioning manifest (one [DeviceModelEntry] per device model). */
data class DeviceModelManifest(val models: List<DeviceModelEntry>) {

    /**
     * The subset the phone should download NOW: entries the PC has (`available`)
     * whose installed artefact is not already present, as judged by [isPresent].
     * Unavailable entries (the PC has not fetched them yet) are skipped silently —
     * the feature stays in honest degraded mode until a later launch finds them.
     */
    fun missing(isPresent: (DeviceModelEntry) -> Boolean): List<DeviceModelEntry> =
        models.filter { it.available && it.installedRelativePath != null && !isPresent(it) }

    companion object {
        /** Parse the `GET /models/device/manifest` JSON body. Tolerant of missing fields. */
        fun parse(json: String): DeviceModelManifest {
            val root = JSONObject(json)
            val arr = root.optJSONArray("models") ?: return DeviceModelManifest(emptyList())
            val out = ArrayList<DeviceModelEntry>(arr.length())
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                val name = o.optString("name").takeIf { it.isNotEmpty() } ?: continue
                out.add(
                    DeviceModelEntry(
                        name = name,
                        kind = o.optString("kind").ifEmpty { null },
                        license = o.optString("license").ifEmpty { null },
                        format = o.optString("format", DeviceModelEntry.FORMAT_FILE)
                            .ifEmpty { DeviceModelEntry.FORMAT_FILE },
                        filename = o.optString("filename").ifEmpty { null },
                        sha256 = o.optString("sha256").ifEmpty { null }
                            ?.takeIf { it != "null" },
                        available = o.optBoolean("available", false),
                        endpoint = o.optString("endpoint").ifEmpty { "/models/device/$name" },
                        targetSubdir = o.optString("target_subdir").ifEmpty { null },
                    ),
                )
            }
            return DeviceModelManifest(out)
        }
    }
}
