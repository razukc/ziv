// The sequencer against the oracle's checked-in timelines: every golden utterance on
// both profiles must reproduce conformance/expected/<name>.<profile>.jsonl exactly —
// text for text, which is stricter than the harness's ±10 ms.
package ziv.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class SequencerGoldenTest {
    private val spec = Repo.spec

    private fun check(profile: String) {
        val goldens = Repo.goldens()
        assertTrue(goldens.size >= 12, "expected the golden set, found ${goldens.size}")
        for ((name, raw) in goldens) {
            val utt = Wire.decodeUtterance(raw)
            val actual = Sequencer.toJsonl(Sequencer.timeline(utt, spec, spec.cellGapDefaultMs, profile))
            assertEquals(Repo.expected(name, profile), actual, "$name on $profile")
        }
    }

    @Test
    fun `every golden matches the reference on single_actuator`() = check("single_actuator")

    @Test
    fun `every golden matches the reference on six_actuator`() = check("six_actuator")

    @Test
    fun `the duration is the end of the close's tail gap`() {
        val u = utt(words = listOf("taxi", "here"), prefix = Prefix("ziv", "double-tap"))
        val beats = Sequencer.timeline(u, spec, spec.cellGapDefaultMs, "single_actuator")
        val close = spec.pattern(Spec.CLOSE_PATTERN)
        val last = beats.last()
        assertEquals(Sequencer.durationMs(u, spec, spec.cellGapDefaultMs, "single_actuator"), last.tMs + last.buzzMs + close.last().gapAfterMs)
    }

    @Test
    fun `the pace is clamped into the envelope`() {
        val u = utt(words = listOf("ab"))
        val slow = Sequencer.timeline(u, spec, 10, "six_actuator")
        val min = Sequencer.timeline(u, spec, spec.cellGapMinMs, "six_actuator")
        assertEquals(min, slow)
        val fast = Sequencer.timeline(u, spec, 100_000, "six_actuator")
        val max = Sequencer.timeline(u, spec, spec.cellGapMaxMs, "six_actuator")
        assertEquals(max, fast)
    }

    @Test
    fun `a slot cell has one beat per raised dot with the dot's bit and the slot width`() {
        val enc = spec.encoding("single_actuator") as Encoding.Slots
        val seg = Sequencer.cellSegment(spec, "t", enc, Phase.CELL, 0, 0, 0)
        assertEquals(listOf(2, 4, 8, 16), seg.beats.map { it.dotMask })
        assertTrue(seg.beats.all { it.buzzMs == enc.slotMs })
        assertEquals(Spec.slotCellMs(enc), seg.lengthMs)
        // slot k starts at k*(slot+gap), plus the column gap after the third slot
        val s = enc.slotMs + enc.slotGapMs
        assertEquals(listOf(1 * s, 2 * s, 3 * s + enc.columnGapMs, 4 * s + enc.columnGapMs), seg.beats.map { it.tMs })
    }

    @Test
    fun `a body_pending utterance plays one working pattern after the cue`() {
        val u = utt(words = emptyList(), bodyPending = true)
        val segs = Sequencer.segments(u, spec, spec.cellGapDefaultMs, "single_actuator")
        assertEquals(listOf(Phase.CUE, Phase.WORKING, Phase.CLOSE), segs.map { it.phase })
    }

    @Test
    fun `the prefix tail resolves a pattern id or a kind name and falls back to the kind's tail`() {
        val k = Kinds.REMINDER
        assertEquals("triple-pulse", Sequencer.tailFor(spec, utt(kind = k, prefix = Prefix("ziv", "triple-pulse"))))
        assertEquals("triple-pulse", Sequencer.tailFor(spec, utt(kind = k, prefix = Prefix("ziv", "reminder"))))
        assertEquals("triple-pulse", Sequencer.tailFor(spec, utt(kind = k, prefix = Prefix("ziv", "nothing-known"))))
    }
}
