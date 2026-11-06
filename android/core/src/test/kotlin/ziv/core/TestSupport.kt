// Shared test helpers: the real spec from the repo root, a fake scheduler, a fake
// transport and utterance builders. Nothing here sleeps for real time.
package ziv.core

import java.io.File

object Repo {
    /** The repository root: the nearest ancestor of the working directory holding docs/haptic-timing.json. */
    val root: File by lazy {
        Main.findSpec(File("."))?.parentFile?.parentFile
            ?: error("docs/haptic-timing.json not found above ${File(".").absolutePath}")
    }

    val specFile: File get() = File(root, "docs/haptic-timing.json")

    val spec: ResolvedSpec by lazy { Spec.parse(specFile.readText()) }

    fun goldens(): List<Pair<String, String>> =
        File(root, "conformance/golden").listFiles { f -> f.name.endsWith(".json") }!!
            .sortedBy { it.name }
            .map { it.name.removeSuffix(".json") to it.readText() }

    fun expected(name: String, profile: String): String =
        File(root, "conformance/expected/$name.$profile.jsonl").readText()

    fun schemaText(name: String): String = File(root, "schema/$name.json").readText()
}

private var seq = 0

fun utt(
    words: List<String> = listOf("hi"),
    kind: String = Kinds.MESSAGE,
    prefix: Prefix? = null,
    bodyPending: Boolean = false,
    specVersion: Int = Repo.spec.version,
    expires: String? = null,
    label: String? = "tests",
): Utterance {
    seq += 1
    return Utterance(
        id = "01TEST" + seq.toString().padStart(6, '0'),
        wearer = "w_1",
        kind = kind,
        from = From("tests", label),
        prefix = prefix,
        words = words,
        bodyPending = bodyPending,
        source = "sender",
        specVersion = specVersion,
        expires = expires,
    )
}

/** A virtual clock with timers. `lateBy` makes every timer fire late, to test self-correction. */
class FakeScheduler : Clock, Timers {
    var now = 0L
    var lateBy = 0L
    private class Timer(val at: Long, val fn: () -> Unit, val id: Int)
    private val timers = ArrayList<Timer>()
    private var seq = 0

    override fun now(): Long = now

    override fun setTimeout(ms: Long, fn: () -> Unit): Any {
        val id = ++seq
        timers.add(Timer(now + maxOf(0L, ms), fn, id))
        return id
    }

    override fun clearTimeout(handle: Any) {
        timers.removeAll { it.id == handle }
    }

    val pending: Int get() = timers.size

    /** Fire every timer due up to `t`, in order, then set the clock to `t`. */
    fun runUntil(t: Long) {
        while (true) {
            timers.sortWith(compareBy({ it.at }, { it.id }))
            val next = timers.firstOrNull() ?: break
            if (next.at > t) break
            timers.removeAt(0)
            now = maxOf(now, next.at + lateBy)
            next.fn()
        }
        now = maxOf(now, t)
    }

    /** Run a bounded horizon forward (re-arming timers such as pings stay pending). */
    fun drain(horizonMs: Long = 120_000) = runUntil(now + horizonMs)

    /** Fire timers until none remain (bounded, so a timer loop fails instead of hanging). */
    fun runAll(limit: Int = 100_000) {
        var n = 0
        while (timers.isNotEmpty()) {
            if (++n > limit) error("FakeScheduler: timers never drained")
            timers.sortWith(compareBy({ it.at }, { it.id }))
            val next = timers.removeAt(0)
            now = maxOf(now, next.at + lateBy)
            next.fn()
        }
    }
}

/** What the device put on the wire, as a readable sequence. */
fun types(frames: List<UpFrame>): List<String> = frames.map {
    when (it) {
        is Progress -> "progress:${it.phase}${it.wordIndex ?: ""}"
        is Nack -> "nack:${it.reason}"
        is Hello -> "hello"
        is Played -> "played"
        is Control -> "control:${it.action}"
        is PrefChanged -> "pref.changed"
        is InputText -> "input.text"
        is Ping -> "ping"
    }
}
