package ziv.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class WordsTest {
    @Test
    fun `letters are lower-cased and digits spelled out`() {
        assertEquals(ComposeResult.Ok(listOf("meds", "nine")), Words.compose("Meds 9"))
        assertEquals(ComposeResult.Ok(listOf("go", "now")), Words.compose("  go   now "))
        assertEquals(ComposeResult.Ok(listOf("room", "one", "two")), Words.compose("room12"))
    }

    @Test
    fun `anything without a cell is refused naming the character`() {
        val r = Words.compose("hi!") as ComposeResult.Refused
        assertTrue(r.reason.startsWith("\"!\""), r.reason)
        assertTrue((Words.compose("") as ComposeResult.Refused).reason.contains("at least one word"))
        assertTrue((Words.compose("a".repeat(33)) as ComposeResult.Refused).reason.contains("longer than 32"))
        assertTrue((Words.compose(List(65) { "a" }.joinToString(" ")) as ComposeResult.Refused).reason.contains("at most 64"))
    }
}
