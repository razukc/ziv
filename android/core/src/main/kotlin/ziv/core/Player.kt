/**
 * The player schedules a timeline against an injectable clock, timer and vibrate
 * sink. Every beat has an absolute deadline (`startAt + t_ms`); each timer is armed
 * for `deadline - now()`, so a late wake-up shortens the next wait instead of
 * pushing every later beat back. Drift never accumulates.
 */
package ziv.core

/** A monotonic millisecond clock. On Android: `SystemClock.uptimeMillis()` under a wake lock. */
fun interface Clock {
    fun now(): Long
}

/** One-shot timers on the same thread the state machine runs on. */
interface Timers {
    fun setTimeout(ms: Long, fn: () -> Unit): Any
    fun clearTimeout(handle: Any)
}

/** The actuator. `vibrate(mask, 0)` must stop any vibration in progress. */
fun interface VibrateSink {
    fun vibrate(dotMask: Int, ms: Int)
}

class PlayOptions(
    /** planned start on the clock; defaults to now. May be in the near future. */
    val startAt: Long? = null,
    /** segment length including its trailing silence; `onDone` fires at `startAt + totalMs` */
    val totalMs: Int,
    val onBeat: ((beat: Beat, index: Int, at: Long) -> Unit)? = null,
    val onDone: ((endAt: Long) -> Unit)? = null,
)

class Player(private val clock: Clock, private val timers: Timers, private val sink: VibrateSink) {
    private class Run(val beats: List<Beat>, val startAt: Long, val total: Int, val opts: PlayOptions) {
        var next = 0
    }

    private var run: Run? = null
    private var timer: Any? = null

    val playing: Boolean get() = run != null

    /** Start a timeline; anything already playing is cut. */
    fun play(beats: List<Beat>, opts: PlayOptions) {
        if (run != null) stop()
        val startAt = opts.startAt ?: clock.now()
        run = Run(beats, startAt, opts.totalMs, opts)
        tick()
    }

    /** Silence now; no further beats or `onDone` from the cut run. */
    fun stop() {
        timer?.let { timers.clearTimeout(it) }
        timer = null
        if (run != null) {
            run = null
            sink.vibrate(0, 0)
        }
    }

    private fun tick() {
        timer = null
        val run = this.run ?: return
        val now = clock.now()
        while (run.next < run.beats.size) {
            val b = run.beats[run.next]
            if (run.startAt + b.tMs > now + TOLERANCE_MS) break
            run.next += 1
            sink.vibrate(b.dotMask, b.buzzMs)
            run.opts.onBeat?.invoke(b, run.next - 1, now)
            if (this.run !== run) return // a callback stopped or replaced this run
        }
        if (run.next >= run.beats.size) {
            val end = run.startAt + run.total
            if (end <= now + TOLERANCE_MS) {
                this.run = null
                run.opts.onDone?.invoke(end)
                return
            }
            timer = timers.setTimeout(maxOf(0L, end - now)) { tick() }
            return
        }
        val due = run.startAt + run.beats[run.next].tMs
        timer = timers.setTimeout(maxOf(0L, due - now)) { tick() }
    }

    companion object {
        /** A timer that wakes this much early still fires the beat (platforms round timers). */
        const val TOLERANCE_MS = 1
    }
}
