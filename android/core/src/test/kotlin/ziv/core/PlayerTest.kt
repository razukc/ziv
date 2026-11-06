// The player under a fake clock: absolute deadlines, no accumulated drift, stop
// silences without onDone, play-while-playing cuts the first run.
package ziv.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class PlayerTest {
    private val beats = listOf(
        Beat(0, 0, 70, "cue"),
        Beat(230, 0, 70, "cue"),
        Beat(720, 19, 230, "cell:h"),
    )

    private class Harness {
        val sched = FakeScheduler()
        val calls = ArrayList<Pair<Long, Int>>()
        val masks = ArrayList<Int>()
        val player = Player(sched, sched) { mask, ms ->
            calls.add(sched.now to ms)
            masks.add(mask)
        }
    }

    @Test
    fun `beats fire in order at their deadlines and onDone at startAt plus total`() {
        val h = Harness()
        var done: Long? = null
        h.player.play(beats, PlayOptions(totalMs = 1500, onDone = { done = it }))
        assertEquals(listOf(0L to 70), h.calls) // the first beat is synchronous
        h.sched.runAll()
        assertEquals(listOf(0L to 70, 230L to 70, 720L to 230), h.calls)
        assertEquals(listOf(0, 0, 19), h.masks)
        assertEquals(1500L, done)
        assertFalse(h.player.playing)
    }

    @Test
    fun `late timers do not accumulate drift`() {
        val h = Harness()
        h.sched.lateBy = 7
        h.player.play(beats, PlayOptions(totalMs = 1500))
        h.sched.runAll()
        // a relative chain (setTimeout(gap) after each beat) would land at 0, 237, 734: 7 ms per hop
        assertEquals(listOf(0L, 237L, 727L), h.calls.map { it.first })
        h.calls.forEachIndexed { i, c -> assertTrue(c.first - beats[i].tMs <= 7, "beat $i drifted") }
    }

    @Test
    fun `a timer that wakes 1 ms early still fires the beat`() {
        val h = Harness()
        h.sched.lateBy = -1
        h.player.play(beats, PlayOptions(totalMs = 1500))
        h.sched.runAll()
        assertEquals(listOf(0L, 229L, 719L), h.calls.map { it.first })
    }

    @Test
    fun `startAt in the future offsets every deadline`() {
        val h = Harness()
        var done: Long? = null
        h.player.play(beats, PlayOptions(startAt = 1000, totalMs = 1500, onDone = { done = it }))
        assertEquals(0, h.calls.size)
        h.sched.runUntil(999)
        assertEquals(0, h.calls.size)
        h.sched.runAll()
        assertEquals(listOf(1000L, 1230L, 1720L), h.calls.map { it.first })
        assertEquals(2500L, done)
    }

    @Test
    fun `stop silences the motor and ends the run without onDone`() {
        val h = Harness()
        var done = false
        h.player.play(beats, PlayOptions(totalMs = 1500, onDone = { done = true }))
        h.sched.runUntil(300)
        h.player.stop()
        assertEquals(300L to 0, h.calls.last())
        h.sched.runAll()
        assertEquals(3, h.calls.size) // 70, 70, then the 0
        assertFalse(done)
        assertFalse(h.player.playing)
    }

    @Test
    fun `play while playing cuts the first run and onBeat reports the index`() {
        val h = Harness()
        val seen = ArrayList<Int>()
        h.player.play(beats, PlayOptions(totalMs = 1500, onBeat = { _, i, _ -> seen.add(i) }))
        h.sched.runUntil(100)
        h.player.play(beats.subList(0, 1), PlayOptions(totalMs = 100, onBeat = { _, i, _ -> seen.add(10 + i) }))
        h.sched.runAll()
        assertEquals(listOf(0, 10), seen)
        assertEquals(listOf(70, 0, 70), h.calls.map { it.second })
        assertNull(h.calls.firstOrNull { it.first > 100 && it.second == 230 })
    }
}
