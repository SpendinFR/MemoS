package com.mlomega.xr.reflexvision

import ai.onnxruntime.OnnxJavaType
import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.nio.LongBuffer
import java.util.concurrent.atomic.AtomicLong

/**
 * MLOmega V19 — E48-A. On-device offline translation reflex (FR↔EN).
 *
 * Translates a short FINAL ASR segment on the phone with ONNX Runtime + a
 * Helsinki-NLP OPUS-MT (MarianMT) model exported to int8 ONNX (Xenova exports,
 * Apache-2.0): an encoder + a merged decoder (KV-cache) driven by greedy
 * autoregressive decoding, tokenised by the pure-Kotlin [MarianTokenizer]. This is
 * a DEVICE reflex — it works with the PC absent, mirroring the offline subtitle
 * path (guide §3.2, E47-A). Only the ASR *finals* are ever translated, never the
 * partials (the caller enforces this).
 *
 * **ONNX Runtime coexistence (ADR §E48-A risk 1).** The sherpa-onnx AAR already
 * ships `libonnxruntime.so` (ORT 1.17.1) but exposes *no* `ai.onnxruntime` Java
 * API — only its own `com.k2fsa.sherpa.onnx` JNI. We add
 * `com.microsoft.onnxruntime:onnxruntime-android:1.17.1` (version-aligned) for the
 * Java API + its `libonnxruntime4j_jni.so`; the duplicate `libonnxruntime.so` is
 * de-duplicated at Unity/Gradle packaging so exactly one (identical) copy ships.
 *
 * **Budget (guide §9.4 on-demand).** Sessions are created lazily on the first
 * translate for a direction and released after [idleReleaseMs] of inactivity via
 * [maybeReleaseIdle] (the caller ticks it), so a reflex that is toggled on but
 * silent costs no memory. Only one direction is resident at a time — switching
 * direction releases the other.
 *
 * **Degraded honesty (invariant).** If the model files for a direction are absent
 * or fail to load, [translate] returns null (no translation), never throws — the
 * subtitle simply shows the original line, and capture is unaffected.
 *
 * Not JVM-testable without the real onnxruntime native lib + the ~108 MB model, so
 * the greedy-decode wiring is validated by an opt-in desktop integration test
 * ([OfflineTranslatorIntegrationTest], skipped unless the models are present); the
 * tokenizer and the direction/lifecycle logic are covered by pure JVM tests.
 */
class OfflineTranslator(
    /** Root under which each direction's model dir lives (e.g. app models root). */
    private val modelsRoot: File,
    /** Release resident sessions after this long with no translate call. */
    private val idleReleaseMs: Long = DEFAULT_IDLE_RELEASE_MS,
    /** Hard cap on generated tokens per segment (short conversational lines). */
    private val maxNewTokens: Int = DEFAULT_MAX_NEW_TOKENS,
    /** onnxruntime intra-op threads (2 keeps latency low without hogging the S25). */
    private val numThreads: Int = 2,
) {
    /** Translation direction. [subdir] matches the provisioned model directory. */
    enum class Direction(val subdir: String, val sourceLang: String, val targetLang: String) {
        FR_EN("opus-mt-fr-en", "fr", "en"),
        EN_FR("opus-mt-en-fr", "en", "fr"),
    }

    private val env: OrtEnvironment by lazy { OrtEnvironment.getEnvironment() }

    // The single resident direction (only one loaded at a time — budget).
    @Volatile private var loaded: Loaded? = null
    private val lastUseMs = AtomicLong(0L)
    private val lock = Any()

    private class Loaded(
        val direction: Direction,
        val encoder: OrtSession,
        val decoder: OrtSession,
        val tokenizer: MarianTokenizer,
    )

    /** True when a target language differs from a segment's language → translate. */
    fun shouldTranslate(segmentLang: String?, targetLang: String?): Boolean {
        if (segmentLang.isNullOrBlank() || targetLang.isNullOrBlank()) return false
        return !segmentLang.equals(targetLang, ignoreCase = true)
    }

    /**
     * Pick the direction that turns [segmentLang] into [targetLang], or null when
     * the pair is not one we ship (only FR↔EN). Pure — the direction table only.
     */
    fun directionFor(segmentLang: String?, targetLang: String?): Direction? {
        val src = segmentLang?.lowercase()
        val tgt = targetLang?.lowercase()
        return when {
            src == "fr" && tgt == "en" -> Direction.FR_EN
            src == "en" && tgt == "fr" -> Direction.EN_FR
            else -> null
        }
    }

    /** Whether a direction's three model files are all present on disk. */
    fun isAvailable(direction: Direction): Boolean {
        val dir = File(modelsRoot, direction.subdir)
        return File(dir, ENCODER_FILE).isFile &&
            File(dir, DECODER_FILE).isFile &&
            File(dir, TOKENIZER_FILE).isFile
    }

    /**
     * Translate one short final segment [text] from [segmentLang] to [targetLang].
     * Returns the translation, or null when translation is not applicable/available
     * (unsupported pair, models absent, blank input, or any load/inference error —
     * honest degraded, never throws). Loads the direction lazily; switching
     * direction releases the previous one.
     */
    fun translate(text: String, segmentLang: String?, targetLang: String?): String? {
        if (text.isBlank()) return null
        val direction = directionFor(segmentLang, targetLang) ?: return null
        return try {
            val active = ensureLoaded(direction) ?: return null
            lastUseMs.set(System.currentTimeMillis())
            val out = runGreedy(active, text)
            out.takeIf { it.isNotBlank() }
        } catch (t: Throwable) {
            // Degraded honesty: no translation, no crash. Drop the (possibly broken)
            // session so a later call can retry from a clean state.
            release()
            null
        }
    }

    /**
     * Release resident sessions if idle for [idleReleaseMs]. The caller ticks this
     * (e.g. from the reflex scheduler); [nowMs] is injectable for tests.
     */
    fun maybeReleaseIdle(nowMs: Long = System.currentTimeMillis()) {
        val last = lastUseMs.get()
        if (loaded != null && last > 0L && nowMs - last >= idleReleaseMs) release()
    }

    /** True while a direction's sessions are resident. */
    fun isLoaded(): Boolean = loaded != null

    /** The currently resident direction, or null. */
    fun loadedDirection(): Direction? = loaded?.direction

    /** Release any resident sessions immediately (idempotent). */
    fun release() {
        synchronized(lock) {
            val l = loaded ?: return
            loaded = null
            try { l.encoder.close() } catch (_: Throwable) {}
            try { l.decoder.close() } catch (_: Throwable) {}
        }
    }

    // ----------------------------------------------------------------------

    private fun ensureLoaded(direction: Direction): Loaded? {
        loaded?.let { if (it.direction == direction) return it }
        synchronized(lock) {
            loaded?.let {
                if (it.direction == direction) return it
                release() // different direction resident → free it first (budget).
            }
            if (!isAvailable(direction)) return null
            val dir = File(modelsRoot, direction.subdir)
            val opts = OrtSession.SessionOptions().apply {
                setIntraOpNumThreads(numThreads)
            }
            val enc = env.createSession(File(dir, ENCODER_FILE).absolutePath, opts)
            val dec = env.createSession(File(dir, DECODER_FILE).absolutePath, opts)
            val tok = MarianTokenizer.fromFile(File(dir, TOKENIZER_FILE))
            val l = Loaded(direction, enc, dec, tok)
            loaded = l
            return l
        }
    }

    /**
     * Greedy autoregressive decode over the merged KV-cache decoder. Mirrors the
     * validated transformers.js control flow (ADR §E48-A): the ENCODER key/value
     * cache is computed once on the first (uncached) decoder step and then FROZEN
     * and re-fed every step (the cached branch does not re-emit it); the DECODER
     * cache grows by one each step. `use_cache_branch` is false on step 0 (all past
     * tensors zero-length) and true thereafter.
     */
    private fun runGreedy(active: Loaded, text: String): String {
        val tok = active.tokenizer
        val inputIds = tok.encode(text)
        val srcLen = inputIds.size

        // --- encoder ---
        val idsArr = LongArray(srcLen) { inputIds[it].toLong() }
        val idsTensor = longTensor(idsArr, longArrayOf(1, srcLen.toLong()))
        val attnArr = LongArray(srcLen) { 1L }
        val attnTensor = longTensor(attnArr, longArrayOf(1, srcLen.toLong()))
        val encOut = active.encoder.run(
            mapOf("input_ids" to idsTensor, "attention_mask" to attnTensor),
        )
        val hidden = encOut.get(0) as OnnxTensor // last_hidden_state [1, srcLen, 512]

        val generated = ArrayList<Int>(maxNewTokens)
        var cur = MarianTokenizer.PAD_ID // decoder_start_token_id
        var decKeys: Array<OnnxTensor?> = arrayOfNulls(NUM_LAYERS * 2) // dec key,value per layer
        var encKeys: Array<OnnxTensor?> = arrayOfNulls(NUM_LAYERS * 2) // frozen after step 0
        val toClose = ArrayList<OnnxTensor>()
        try {
            var step = 0
            while (step < maxNewTokens) {
                val useCache = step > 0
                val feed = HashMap<String, OnnxTensor>()
                feed["encoder_attention_mask"] = attnTensor
                val curTensor = longTensor(longArrayOf(cur.toLong()), longArrayOf(1, 1)).also { toClose.add(it) }
                feed["input_ids"] = curTensor
                feed["encoder_hidden_states"] = hidden
                feed["use_cache_branch"] = boolTensor(useCache).also { toClose.add(it) }
                for (l in 0 until NUM_LAYERS) {
                    if (useCache) {
                        feed["past_key_values.$l.decoder.key"] = decKeys[l * 2]!!
                        feed["past_key_values.$l.decoder.value"] = decKeys[l * 2 + 1]!!
                        feed["past_key_values.$l.encoder.key"] = encKeys[l * 2]!!
                        feed["past_key_values.$l.encoder.value"] = encKeys[l * 2 + 1]!!
                    } else {
                        val z = emptyKv().also { toClose.add(it) }
                        feed["past_key_values.$l.decoder.key"] = z
                        feed["past_key_values.$l.decoder.value"] = z
                        feed["past_key_values.$l.encoder.key"] = z
                        feed["past_key_values.$l.encoder.value"] = z
                    }
                }
                val decOut = active.decoder.run(feed)
                val logits = decOut.get("logits").get() as OnnxTensor
                val next = argmaxLastRow(logits, tok.vocabSize)
                if (next == tok.eosId) { decOut.close(); break }
                generated.add(next)

                // Rotate KV caches: decoder grows, encoder frozen from step 0.
                val newDec: Array<OnnxTensor?> = arrayOfNulls(NUM_LAYERS * 2)
                for (l in 0 until NUM_LAYERS) {
                    newDec[l * 2] = decOut.get("present.$l.decoder.key").get() as OnnxTensor
                    newDec[l * 2 + 1] = decOut.get("present.$l.decoder.value").get() as OnnxTensor
                    if (!useCache) {
                        encKeys[l * 2] = decOut.get("present.$l.encoder.key").get() as OnnxTensor
                        encKeys[l * 2 + 1] = decOut.get("present.$l.encoder.value").get() as OnnxTensor
                    }
                }
                // Close the previous decoder-cache tensors we no longer need (the
                // encoder cache is a separate, frozen array — never closed here).
                for (t in decKeys) try { t?.close() } catch (_: Throwable) {}
                decKeys = newDec
                cur = next
                step++
            }
        } finally {
            for (t in toClose) try { t.close() } catch (_: Throwable) {}
            for (t in decKeys) try { t?.close() } catch (_: Throwable) {}
            for (t in encKeys) try { t?.close() } catch (_: Throwable) {}
            // `hidden` is owned by `encOut` (get(0)); closing the result frees it.
            try { encOut.close() } catch (_: Throwable) {}
            try { idsTensor.close() } catch (_: Throwable) {}
            try { attnTensor.close() } catch (_: Throwable) {}
        }
        return tok.decode(generated.toIntArray())
    }

    // --- ORT tensor helpers ---------------------------------------------------

    private fun longTensor(data: LongArray, shape: LongArray): OnnxTensor =
        OnnxTensor.createTensor(env, LongBuffer.wrap(data), shape)

    private fun boolTensor(v: Boolean): OnnxTensor {
        // No boolean-array overload in the ORT Java API: a BOOL tensor is created
        // from a single-byte direct buffer (0/1) with an explicit OnnxJavaType.
        val bb = ByteBuffer.allocateDirect(1).order(ByteOrder.nativeOrder())
        bb.put(if (v) 1.toByte() else 0.toByte())
        bb.rewind()
        return OnnxTensor.createTensor(env, bb, longArrayOf(1), OnnxJavaType.BOOL)
    }

    /** Zero-length KV tensor [1, heads, 0, headDim] for the uncached first step. */
    private fun emptyKv(): OnnxTensor =
        OnnxTensor.createTensor(env, FloatBuffer.allocate(0), longArrayOf(1, NUM_HEADS.toLong(), 0, HEAD_DIM.toLong()))

    /** argmax over the last decoder row of the logits tensor [1, seq, vocab]. */
    private fun argmaxLastRow(logits: OnnxTensor, vocab: Int): Int {
        val buf = logits.floatBuffer
        val total = buf.capacity()
        val start = total - vocab // last row
        var bestIdx = 0
        var bestVal = Float.NEGATIVE_INFINITY
        var i = 0
        while (i < vocab) {
            val v = buf.get(start + i)
            if (v > bestVal) { bestVal = v; bestIdx = i }
            i++
        }
        return bestIdx
    }

    companion object {
        const val DEFAULT_IDLE_RELEASE_MS = 60_000L
        const val DEFAULT_MAX_NEW_TOKENS = 64

        // OPUS-MT (Marian) base geometry, from the ONNX decoder signature.
        const val NUM_LAYERS = 6
        const val NUM_HEADS = 8
        const val HEAD_DIM = 64

        const val ENCODER_FILE = "encoder_model_int8.onnx"
        const val DECODER_FILE = "decoder_model_merged_int8.onnx"
        const val TOKENIZER_FILE = "tokenizer.json"
    }
}
