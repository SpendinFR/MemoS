package com.mlomega.xr.reflexvision

import java.text.Normalizer

/**
 * E58 — wake-word detection over the on-device **French ASR transcript**.
 *
 * The sherpa [KeywordSpotter] (KWS) is an English-BPE model: it mispronounces
 * French wake words like "viki"/"jarvis" and misses them. Rather than the KWS,
 * E58 watches the FR ASR final transcript that already runs on device and fires
 * the wake word when it appears there. This matcher is the pure decision core.
 *
 * **Matching contract.** Both the transcript and the wake word are normalised —
 * lower-cased, accents stripped (é→e, ï→i, ç→c…), punctuation removed, runs of
 * whitespace collapsed. The wake word must then appear as a *token* (whole word)
 * in the transcript, not merely a substring: "viki" matches "dis viki maintenant"
 * but NOT "vikings" (which is a different, longer token). A light fuzziness is
 * allowed to absorb ASR spelling drift: a transcript token matches the wake word
 * when their Levenshtein edit distance is within a length-dependent budget
 * ([editBudget]) — for a normal wake word (≥4 letters) that budget is 2, so
 * "vicky"/"viqui" match "viki" while the longer unrelated token "vikings"
 * (distance 3) and clearly different words ("bonjour") do not. Very short tokens
 * (≤3 letters) must match exactly.
 *
 * An empty (blank) wake word never matches. Multi-word wake words are supported:
 * every token of the wake word must be matched, in order and contiguously,
 * against a run of transcript tokens (each pair within the per-token edit budget).
 *
 * Pure and JVM-testable ([WakeWordMatcherTest]); no Android / sherpa types here.
 */
object WakeWordMatcher {

    /**
     * True if [wakeWord] is spoken inside [transcript] under the normalise +
     * whole-token + light-Levenshtein rules documented on this object. A blank
     * [wakeWord] always returns false.
     */
    fun matches(transcript: String, wakeWord: String): Boolean {
        val wakeTokens = tokenize(wakeWord)
        if (wakeTokens.isEmpty()) return false
        val textTokens = tokenize(transcript)
        if (textTokens.size < wakeTokens.size) return false

        // Slide the wake-word token run over the transcript tokens; every token
        // pair must be within its own length-dependent edit budget.
        val last = textTokens.size - wakeTokens.size
        for (start in 0..last) {
            var all = true
            for (i in wakeTokens.indices) {
                val w = wakeTokens[i]
                if (levenshtein(textTokens[start + i], w) > editBudget(w)) {
                    all = false
                    break
                }
            }
            if (all) return true
        }
        return false
    }

    /**
     * Normalise then split into whole-word tokens: lower-case, strip accents,
     * drop everything that is not a letter or digit (punctuation, symbols),
     * collapse whitespace. Returns the ordered, non-empty tokens.
     */
    fun tokenize(text: String): List<String> {
        if (text.isBlank()) return emptyList()
        val ascii = stripAccents(text.lowercase())
        return ascii
            .split(Regex("[^\\p{L}\\p{Nd}]+"))
            .filter { it.isNotEmpty() }
    }

    /**
     * Length-dependent edit-distance budget for one token.
     *
     * A very short token (≤3 letters) must match exactly: even a single edit on a
     * 2–3 letter word collapses distinct words ("go"/"va", "oui"/"non"). From 4
     * letters up the budget is 2, which is what absorbs realistic French-ASR
     * spelling drift on the typical wake word: for "viki" it admits "vicky" and
     * "viqui" (edit distance 2) while still rejecting the unrelated longer token
     * "vikings" (distance 3) and anything further ("bonjour", "merci"). The budget
     * is capped at 2 so long words never open up to many-edit false triggers.
     *
     * Note (E58): the ADR sketch suggested a ≤1 budget for 3–5 letter words, but
     * its own acceptance examples ("vicky"/"viqui" → match "viki") are distance 2,
     * so the budget is 2 for those lengths — the concrete examples are binding.
     */
    fun editBudget(token: String): Int = if (token.length <= 3) 0 else 2

    /** Strip combining diacritics after NFD decomposition (é→e, ï→i, ç→c…). */
    private fun stripAccents(s: String): String {
        val decomposed = Normalizer.normalize(s, Normalizer.Form.NFD)
        return decomposed.replace(Regex("\\p{Mn}+"), "")
    }

    /** Classic iterative Levenshtein edit distance (two-row, O(n) memory). */
    private fun levenshtein(a: String, b: String): Int {
        if (a == b) return 0
        if (a.isEmpty()) return b.length
        if (b.isEmpty()) return a.length
        var prev = IntArray(b.length + 1) { it }
        var curr = IntArray(b.length + 1)
        for (i in 1..a.length) {
            curr[0] = i
            val ca = a[i - 1]
            for (j in 1..b.length) {
                val cost = if (ca == b[j - 1]) 0 else 1
                curr[j] = minOf(
                    prev[j] + 1,        // deletion
                    curr[j - 1] + 1,    // insertion
                    prev[j - 1] + cost, // substitution
                )
            }
            val tmp = prev; prev = curr; curr = tmp
        }
        return prev[b.length]
    }
}
