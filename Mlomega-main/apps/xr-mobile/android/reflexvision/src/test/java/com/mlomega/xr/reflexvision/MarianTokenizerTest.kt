package com.mlomega.xr.reflexvision

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure-JVM tests for [MarianTokenizer] — the E48-A Unigram (Marian/OPUS-MT)
 * tokenizer. Uses a small hand-authored `tokenizer.json` in the exact shape of the
 * Xenova OPUS-MT exports (Unigram model: `vocab` = list of `[token, log_score]`,
 * `unk_id`), so encode/decode round-trips are proved without the 5 MB real file or
 * any SentencePiece JNI (ADR §E48-A risk 2). The `▁` metaspace marker is the
 * SentencePiece `▁` the exports use.
 */
class MarianTokenizerTest {

    private val ms = "▁" // ▁

    /**
     * A minimal but real-format Unigram vocab. Ids 0/1/2 are the OPUS-MT specials
     * (</s>, <unk> placeholder, <unk>); the rest are `▁`-prefixed word pieces and
     * suffixes chosen so "hello world" and "the cat" segment cleanly, and so a
     * multi-piece word ("cats" = "▁cat" + "s") exercises Viterbi.
     */
    private val json = """
        {
          "model": {
            "type": "Unigram",
            "unk_id": 2,
            "vocab": [
              ["</s>", 0.0],
              ["<pad-lo>", 0.0],
              ["<unk>", 0.0],
              ["${ms}hello", -1.0],
              ["${ms}world", -1.0],
              ["${ms}the", -0.5],
              ["${ms}cat", -2.0],
              ["${ms}cats", -6.0],
              ["s", -3.0],
              ["${ms}a", -2.5],
              ["b", -4.0]
            ]
          }
        }
    """.trimIndent()

    private fun tok() = MarianTokenizer.fromJson(json)

    @Test
    fun `encode segments words with metaspace and appends eos`() {
        val t = tok()
        val ids = t.encode("hello world")
        // ▁hello(3) ▁world(4) </s>(0)
        assertEquals(listOf(3, 4, 0), ids.toList())
        assertEquals(t.eosId, ids.last())
    }

    @Test
    fun `decode restores spaces and drops specials`() {
        val t = tok()
        assertEquals("hello world", t.decode(intArrayOf(3, 4, 0)))
        // pad + eos are stripped; leading space trimmed.
        assertEquals("the cat", t.decode(intArrayOf(5, 6, 0, MarianTokenizer.PAD_ID)))
    }

    @Test
    fun `encode decode round-trips a phrase`() {
        val t = tok()
        val text = "the cat"
        val ids = t.encode(text)
        // Drop the trailing eos for a text-level round-trip.
        val body = ids.copyOf(ids.size - 1)
        assertEquals(text, t.decode(body))
    }

    @Test
    fun `viterbi prefers the higher-scoring segmentation`() {
        val t = tok()
        // "cats": either ▁cats(-6) OR ▁cat(-2)+s(-3) = -5 → the split wins.
        val ids = t.encode("cats")
        assertEquals(listOf(6, 8, 0), ids.toList()) // ▁cat, s, </s>
    }

    @Test
    fun `whitespace is collapsed before segmentation`() {
        val t = tok()
        assertEquals(listOf(3, 4, 0), t.encode("  hello   world  ").toList())
    }

    @Test
    fun `unknown characters fall back to unk without throwing`() {
        val t = tok()
        // 'z' is not representable → unk id 2 appears, still terminates with eos.
        val ids = t.encode("z")
        assertTrue(ids.contains(t.unkId))
        assertEquals(t.eosId, ids.last())
    }

    @Test
    fun `blank input encodes to just eos`() {
        val t = tok()
        assertEquals(listOf(0), t.encode("   ").toList())
        assertEquals(listOf(0), t.encode("").toList())
    }

    @Test
    fun `vocab size and eos are exposed`() {
        val t = tok()
        assertEquals(11, t.vocabSize)
        assertEquals(0, t.eosId)
        assertEquals(2, t.unkId)
    }

    @Test
    fun `decode ignores out-of-range ids defensively`() {
        val t = tok()
        assertFalse(t.decode(intArrayOf(999999, 3)).contains("999999"))
        assertEquals("hello", t.decode(intArrayOf(-5, 3, 424242)))
    }
}
