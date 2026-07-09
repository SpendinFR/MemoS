package com.mlomega.xr.reflexvision

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * E58 — device-free tests of wake-word detection over the FR ASR transcript.
 * Pure JUnit, deterministic (no audio, no sherpa). See [WakeWordMatcher].
 */
class WakeWordMatcherTest {

    // --- basic whole-token match -----------------------------------------

    @Test
    fun `wake word present as a token matches`() {
        assertTrue(WakeWordMatcher.matches("dis viki", "viki"))
        assertTrue(WakeWordMatcher.matches("viki", "viki"))
        assertTrue(WakeWordMatcher.matches("ok viki tu m entends", "viki"))
    }

    @Test
    fun `wake word absent does not match`() {
        assertFalse(WakeWordMatcher.matches("bonjour tout le monde", "viki"))
        assertFalse(WakeWordMatcher.matches("", "viki"))
    }

    // --- accents / case / punctuation ------------------------------------

    @Test
    fun `case and punctuation are normalised`() {
        assertTrue(WakeWordMatcher.matches("Viki !", "viki"))
        assertTrue(WakeWordMatcher.matches("VIKI, tu es la ?", "viki"))
        assertTrue(WakeWordMatcher.matches("... viki ...", "VIKI"))
    }

    @Test
    fun `accents are stripped on both sides`() {
        // transcript carries an accent, wake word does not (and vice-versa)
        assertTrue(WakeWordMatcher.matches("dis vïki", "viki"))
        assertTrue(WakeWordMatcher.matches("active méléa", "melea"))
        assertTrue(WakeWordMatcher.matches("active melea", "méléa"))
    }

    // --- light Levenshtein tolerance -------------------------------------

    @Test
    fun `close spelling variants within one edit match`() {
        assertTrue(WakeWordMatcher.matches("dis vicky", "viki")) // substitution
        assertTrue(WakeWordMatcher.matches("dis viqui", "viki")) // substitution
        assertTrue(WakeWordMatcher.matches("dis vik", "viki"))   // deletion
        assertTrue(WakeWordMatcher.matches("dis vikii", "viki")) // insertion
    }

    @Test
    fun `longer unrelated token is not a substring match`() {
        // "vikings" differs from "viki" by 3 edits — beyond the budget, so no
        // false trigger even though "viki" is a substring of it.
        assertFalse(WakeWordMatcher.matches("les vikings arrivent", "viki"))
    }

    @Test
    fun `clearly different word does not match`() {
        assertFalse(WakeWordMatcher.matches("bonjour", "viki"))
        assertFalse(WakeWordMatcher.matches("merci beaucoup", "viki"))
    }

    // --- empty wake word --------------------------------------------------

    @Test
    fun `empty or blank wake word never matches`() {
        assertFalse(WakeWordMatcher.matches("dis viki", ""))
        assertFalse(WakeWordMatcher.matches("dis viki", "   "))
        assertFalse(WakeWordMatcher.matches("", ""))
    }

    // --- multi-word wake word --------------------------------------------

    @Test
    fun `multi word wake phrase matches contiguous tokens`() {
        assertTrue(WakeWordMatcher.matches("dis hey mlomega maintenant", "hey mlomega"))
        assertTrue(WakeWordMatcher.matches("Hey, Mlomega !", "hey mlomega"))
    }

    @Test
    fun `multi word wake phrase needs all tokens`() {
        assertFalse(WakeWordMatcher.matches("dis mlomega", "hey mlomega"))
        // tokens present but not contiguous → no match
        assertFalse(WakeWordMatcher.matches("hey toi mlomega", "hey mlomega"))
    }

    // --- short wake word: no fuzzy budget --------------------------------

    @Test
    fun `very short wake word matches exactly only`() {
        assertTrue(WakeWordMatcher.matches("dis go", "go"))
        // 2-letter word: 1 edit would collapse "go"/"va" — must be exact.
        assertFalse(WakeWordMatcher.matches("dis va", "go"))
    }
}
