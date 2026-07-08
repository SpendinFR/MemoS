package com.mlomega.xr.reflexvision

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * MLOmega V19 — E48-A. Pure-Kotlin Marian / OPUS-MT tokenizer.
 *
 * The offline translation reflex ([OfflineTranslator]) runs Helsinki-NLP OPUS-MT
 * (MarianMT) exported to ONNX by Xenova. Its tokenizer is a SentencePiece
 * **Unigram** model, but we do NOT depend on any SentencePiece JNI (`.spm`
 * binaries, `ai.djl.sentencepiece`): those are desktop-oriented and ship no
 * reliable Android binaries (ADR §E48-A risk 2). Instead this reimplements the
 * exact Unigram pipeline directly from the export's `tokenizer.json`, which is
 * pure text/JSON and therefore fully JVM-testable ([MarianTokenizerTest]).
 *
 * Pipeline (matches HuggingFace tokenizers for these OPUS-MT exports):
 *   * pre-tokenizer = WhitespaceSplit + Metaspace(`▁`, add_prefix_space): collapse
 *     runs of whitespace, prepend a space, then map every space to `▁`;
 *   * model = Unigram: Viterbi segmentation maximising the sum of token
 *     log-scores over the `▁`-joined string, unknown spans fall back to `unk_id`;
 *   * post-processing appends the eos token `</s>` (id 0).
 *   * decode maps ids → tokens, concatenates, turns `▁` back into spaces, trims.
 *
 * No Android imports — only `org.json` (provided by the platform at runtime, by
 * the `org.json:json` test dep on the JVM), so encode/decode round-trips are
 * proved on the plain JVM against the real vocab.
 */
class MarianTokenizer private constructor(
    private val idToToken: Array<String>,
    private val tokenToId: HashMap<String, Int>,
    private val scores: FloatArray,
    val unkId: Int,
    private val maxTokenLen: Int,
) {
    /** eos token id (`</s>`) appended to every encoded sequence; also stops decode. */
    val eosId: Int get() = EOS_ID

    /** Vocabulary size (== the decoder logits dimension). */
    val vocabSize: Int get() = idToToken.size

    /**
     * Encode [text] to token ids, terminated by [eosId]. Whitespace is collapsed,
     * a leading space is added (Metaspace add_prefix_space), spaces become `▁`, and
     * the `▁`-string is segmented by Unigram Viterbi. An unrepresentable single
     * character maps to [unkId]. Empty / blank input yields just `[eosId]`.
     */
    fun encode(text: String): IntArray {
        val s = metaspace(text)
        if (s.isEmpty()) return intArrayOf(EOS_ID)
        val ids = viterbi(s)
        val out = IntArray(ids.size + 1)
        for (i in ids.indices) out[i] = ids[i]
        out[ids.size] = EOS_ID
        return out
    }

    /**
     * Decode token [ids] back to text: skip the eos/pad specials, map ids → tokens,
     * concatenate, restore `▁` → space, trim. Out-of-range ids are skipped
     * defensively (never throws).
     */
    fun decode(ids: IntArray): String {
        val sb = StringBuilder()
        for (id in ids) {
            if (id == EOS_ID || id == PAD_ID) continue
            if (id < 0 || id >= idToToken.size) continue
            sb.append(idToToken[id])
        }
        return sb.toString().replace(METASPACE, ' ').trim()
    }

    /** Collapse whitespace, add a leading space, map spaces → `▁` (Metaspace). */
    private fun metaspace(text: String): String {
        val collapsed = text.trim().replace(WS_RUN, " ")
        if (collapsed.isEmpty()) return ""
        return (METASPACE + collapsed.replace(' ', METASPACE))
    }

    /**
     * Unigram Viterbi over the `▁`-joined string [s]: for each prefix boundary pick
     * the segmentation maximising the summed token log-score. Falls back to a
     * single-character unk span when no in-vocab token ends at a position, so the
     * segmentation is always total. Operates on Unicode code points via char
     * indices (the vocab tokens are stored as their raw substrings).
     */
    private fun viterbi(s: String): IntArray {
        val n = s.length
        val best = DoubleArray(n + 1) { NEG_INF }
        val back = IntArray(n + 1) { -1 }
        val bestId = IntArray(n + 1) { -1 }
        best[0] = 0.0
        for (i in 1..n) {
            val lo = maxOf(0, i - maxTokenLen)
            var j = lo
            while (j < i) {
                if (best[j] > NEG_INF) {
                    val id = tokenToId[s.substring(j, i)]
                    if (id != null) {
                        val cand = best[j] + scores[id]
                        if (cand > best[i]) {
                            best[i] = cand; back[i] = j; bestId[i] = id
                        }
                    }
                }
                j++
            }
            if (best[i] <= NEG_INF) {
                // No token ends here: consume one char as unk (keeps it total).
                val j0 = i - 1
                best[i] = best[j0] + scores[unkId] - UNK_PENALTY
                back[i] = j0
                bestId[i] = unkId
            }
        }
        // Backtrack.
        val rev = ArrayList<Int>()
        var i = n
        while (i > 0) {
            rev.add(bestId[i]); i = back[i]
        }
        val out = IntArray(rev.size)
        for (k in rev.indices) out[k] = rev[rev.size - 1 - k]
        return out
    }

    companion object {
        /** SentencePiece metaspace marker `▁` (U+2581). */
        const val METASPACE = '▁'

        // Fixed special-token ids for the OPUS-MT exports (config.json):
        //   </s> = 0 (eos), <unk> = 2, <pad> = 59513 (== decoder_start_token_id).
        const val EOS_ID = 0
        const val PAD_ID = 59513

        private const val NEG_INF = -1.0e18
        // Discourage the unk fallback vs any real segmentation without forbidding it.
        private const val UNK_PENALTY = 10.0
        private val WS_RUN = Regex("\\s+")

        /** Build from an on-device `tokenizer.json` file. */
        fun fromFile(tokenizerJson: File): MarianTokenizer =
            fromJson(tokenizerJson.readText(Charsets.UTF_8))

        /**
         * Build from the raw `tokenizer.json` text. Reads `model.vocab` (a JSON
         * array of `[token, log_score]`) and `model.unk_id`. Tolerant of the two
         * special-token entries the OPUS-MT vocab starts with.
         */
        fun fromJson(json: String): MarianTokenizer {
            val root = JSONObject(json)
            val model = root.getJSONObject("model")
            val vocab: JSONArray = model.getJSONArray("vocab")
            val unkId = model.optInt("unk_id", 2)
            val n = vocab.length()
            val idToToken = Array(n) { "" }
            val tokenToId = HashMap<String, Int>(n * 2)
            val scores = FloatArray(n)
            var maxLen = 1
            for (i in 0 until n) {
                val pair = vocab.getJSONArray(i)
                val tok = pair.getString(0)
                val score = pair.getDouble(1).toFloat()
                idToToken[i] = tok
                scores[i] = score
                // First id wins on the rare duplicate token (SentencePiece specials).
                if (!tokenToId.containsKey(tok)) tokenToId[tok] = i
                if (tok.length > maxLen) maxLen = tok.length
            }
            return MarianTokenizer(idToToken, tokenToId, scores, unkId, maxLen)
        }
    }
}
