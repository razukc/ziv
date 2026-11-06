// The device state machine against a fake transport (a list of frames) and a fake
// clock: the hello-first handshake, progress/played ordering, nack paths, cancel
// handling, resume with held ids, body_pending, interjected cues, advance modes, the
// controls and prefs both ways. `muted` stands where the web client has `hidden`.
package ziv.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DeviceTest {
    private val spec = Repo.spec
    private val key = "k".repeat(32)

    private class Rig(
        seed: QueueSnapshot? = null,
        queueCap: Int = DEFAULT_QUEUE_CAP,
        bodyTimeoutMs: Long = DEFAULT_BODY_TIMEOUT_MS,
        wall: () -> Long = { 1_700_000_000_000L },
    ) {
        val sched = FakeScheduler()
        val frames = ArrayList<UpFrame>()
        val vibrations = ArrayList<Int>()
        var muted = false
        val store = MemoryQueueStore().also { s -> seed?.let { s.save(it) } }
        val log = ArrayList<String>()
        val player = Player(sched, sched) { _, ms -> vibrations.add(ms) }
        val device = Device(
            DeviceDeps(
                spec = Repo.spec, profile = "single_actuator", player = player, store = store, clock = sched, timers = sched,
                send = { frames.add(it) }, isMuted = { muted }, wallClock = wall, log = { log.add(it) },
                queueCap = queueCap, bodyTimeoutMs = bodyTimeoutMs,
            ),
        ).also { it.restore() }

        /** The socket opened: hello goes first, then the relay's ack. */
        fun connect(key: String, prefs: Prefs = Prefs(), resend: List<Utterance> = emptyList()) {
            frames.add(device.hello(key))
            device.handleFrame(HelloAck(wearer = "w_1", device = "d_test", specVersion = Repo.spec.version, prefs = prefs, resend = resend))
        }

        fun open(u: Utterance) = device.handleFrame(UtteranceOpen(u))
        fun since(n: Int): List<String> = types(frames.subList(n, frames.size))
        fun played(): List<Played> = frames.filterIsInstance<Played>()
        fun progressFor(id: String): List<String> = frames.filterIsInstance<Progress>().filter { it.id == id }.map { "${it.phase}${it.wordIndex ?: ""}" }
    }

    @Test
    fun `hello is the first frame, then progress at cue, each word and close, then played`() {
        val r = Rig()
        r.connect(key, Prefs(paceMs = 420, advance = Advance.AUTO))
        val hello = r.frames[0] as Hello
        assertEquals("single_actuator", hello.profile)
        assertEquals(spec.version, hello.specVersion)
        assertEquals(spec.cellGapDefaultMs, hello.paceMs)
        assertNull(hello.lastAcked)
        assertEquals(emptyList(), hello.held)
        assertEquals(key, hello.deviceKey)

        val u = utt(words = listOf("meds", "nine"), prefix = Prefix("ziv", "double-tap"))
        r.open(u)
        assertEquals(u.id, r.device.view().current?.id)
        assertEquals(1, r.frames.size, "with a prefix, nothing is reported before the cue")
        r.sched.drain()
        assertEquals(listOf("progress:cue", "progress:word0", "progress:word1", "progress:close", "played"), r.since(1))
        val played = r.frames.last() as Played
        assertEquals(u.id, played.id)
        assertEquals(Sequencer.durationMs(u, spec, 420, "single_actuator").toLong(), played.closedMs - played.startedMs)
        val expected = Sequencer.timeline(u, spec, 420, "single_actuator")
        assertEquals(expected.map { it.buzzMs }, r.vibrations)
        assertEquals(u.id, r.device.lastAckedId)
        assertEquals(emptyList(), r.device.held)
        assertEquals("idle", r.device.view().phase)
    }

    @Test
    fun `a fresh hello carries last_acked and the held ids`() {
        val r = Rig()
        r.connect(key)
        val a = utt(words = listOf("hi"))
        r.open(a)
        r.sched.drain()
        assertEquals(1, r.played().size)
        val hello = r.device.hello(key)
        assertEquals(a.id, hello.lastAcked)
        assertEquals(emptyList(), hello.held)

        r.device.setAdvance(Advance.TAP, false)
        val b = utt(words = listOf("one"))
        val c = utt(words = listOf("two"))
        r.open(b)
        r.open(c)
        r.sched.drain() // b plays, c waits for the tap
        assertEquals(listOf(c.id), r.device.hello(key).held)
        assertEquals(b.id, r.device.hello(key).lastAcked)
    }

    @Test
    fun `muted - an open is refused with nack muted, going muted mid-utterance stops and nacks, a resend plays`() {
        val r = Rig()
        r.connect(key)
        r.muted = true
        val a = utt(words = listOf("hi"))
        r.open(a)
        assertEquals(listOf("nack:muted"), r.since(1))
        assertEquals(0, r.vibrations.size)
        assertEquals(emptyList(), r.device.held)

        r.muted = false
        val b = utt(words = listOf("hello", "world"))
        r.open(b)
        r.sched.runUntil(r.sched.now + 1500) // into the first word
        assertTrue(r.vibrations.size > 2)
        r.muted = true
        r.device.onMuted(true)
        assertTrue(r.frames.any { it is Nack && it.id == b.id && it.reason == Reasons.MUTED })
        assertEquals(0, r.vibrations.last(), "vibrate(0) silences the motor")
        assertEquals(emptyList(), r.device.held)
        val n = r.vibrations.size
        r.sched.drain()
        assertEquals(n, r.vibrations.size, "nothing plays while muted")

        r.muted = false
        r.device.onMuted(false)
        r.open(b) // the relay resends; the device plays it
        r.sched.drain()
        assertEquals(listOf("cue", "word0", "cue", "word0", "word1", "close"), r.progressFor(b.id))
        assertEquals(1, r.played().count { it.id == b.id })
    }

    @Test
    fun `cancel removes a queued utterance and stops the current one`() {
        val r = Rig()
        r.connect(key)
        val a = utt(words = listOf("hello"))
        val b = utt(words = listOf("world"))
        r.open(a)
        r.open(b)
        r.device.handleFrame(UtteranceCancel(b.id, Reasons.CANCELLED_BY_SENDER))
        assertEquals(listOf(a.id), r.device.held)
        r.sched.drain()
        assertEquals(1, r.played().count { it.id == a.id })
        assertFalse(r.frames.any { it is Progress && it.id == b.id }, "b was never announced")

        val c = utt(words = listOf("again"))
        r.open(c)
        r.sched.runUntil(r.sched.now + 1000)
        val n = r.vibrations.size
        r.device.handleFrame(UtteranceCancel(c.id, Reasons.CANCELLED_BY_SENDER))
        assertEquals(0, r.vibrations.last())
        assertEquals(emptyList(), r.device.held)
        r.sched.drain()
        assertEquals(n + 1, r.vibrations.size)
        assertFalse(r.played().any { it.id == c.id })
        assertEquals("idle", r.device.view().phase)
    }

    @Test
    fun `a restart resumes - hello carries held ids and last_acked, then the held utterances play`() {
        val held = listOf(utt(words = listOf("one")), utt(words = listOf("two")))
        val r = Rig(seed = QueueSnapshot(held.map { HeldEntry(it, null, cued = true, receivedAt = 0) }, lastAcked = "01TESTACKED"))
        r.connect(key)
        val hello = r.frames[0] as Hello
        assertEquals(held.map { it.id }, hello.held)
        assertEquals("01TESTACKED", hello.lastAcked)
        r.sched.drain()
        assertEquals(
            listOf(
                "progress:cue", "progress:word0", "progress:close", "played",
                "progress:cue", "progress:word0", "progress:close", "played",
            ),
            r.since(1),
        )
        assertEquals(held[1].id, r.store.load().lastAcked)
        assertEquals(emptyList(), r.store.load().entries)
    }

    @Test
    fun `spec mismatch, duplicates and a full queue are refused loudly`() {
        val r = Rig(queueCap = 1)
        r.connect(key)
        r.open(utt(words = listOf("hi"), specVersion = 99))
        assertEquals(listOf("nack:spec_mismatch"), r.since(1))
        val a = utt(words = listOf("hi"))
        r.open(a)
        r.open(a)
        r.open(utt(words = listOf("no")))
        assertTrue(r.frames.any { it is Nack && it.reason == Reasons.QUEUE_FULL })
        assertTrue(r.log.any { it.contains("duplicate") })
        assertEquals(listOf(a.id), r.device.held)
        r.sched.drain()
        assertEquals(1, r.played().size)
    }

    @Test
    fun `body_pending - working repeats on the device clock until the body comes, then the words`() {
        val r = Rig()
        r.connect(key)
        val a = utt(kind = Kinds.REMINDER, words = emptyList(), bodyPending = true, prefix = Prefix("ziv", "triple-pulse"))
        r.open(a)
        assertEquals(a.id, r.device.view().current?.id)
        r.sched.runUntil(r.sched.now + 9000) // prefix, cue, then a few working repeats
        assertTrue(r.frames.any { it is Progress && it.phase == Phases.WORKING })
        val workingBeats = r.vibrations.size
        assertTrue(workingBeats >= 7, "expected repeats of the working pattern, saw $workingBeats beats")
        assertEquals("working", r.device.view().phase)
        assertTrue(r.device.view().current!!.bodyPending)
        r.device.handleFrame(UtteranceBody(a.id, words = listOf("meds", "now")))
        r.sched.drain()
        val t = r.since(1)
        assertEquals(listOf("progress:cue", "progress:word0", "progress:word1", "progress:close", "played"), t.filter { it != "progress:working" })
        assertEquals(1, t.count { it == "progress:working" })
        assertEquals(emptyList(), r.store.load().entries, "a played utterance leaves the persisted queue")
        assertEquals(a.id, r.store.load().lastAcked)
    }

    @Test
    fun `working repeats every working_every_ms`() {
        val r = Rig()
        r.connect(key)
        val a = utt(words = emptyList(), bodyPending = true)
        r.open(a)
        val starts = ArrayList<Long>()
        // the cue plays first; collect the start of each working pattern from the vibration timing
        val cue = Sequencer.cueSegment(spec, Kinds.MESSAGE)
        r.sched.runUntil(cue.totalMs.toLong() - 1)
        val before = r.vibrations.size
        val working = spec.pattern(Spec.WORKING_PATTERN)
        for (k in 0 until 3) {
            val at = cue.totalMs + k * spec.workingEveryMs
            r.sched.runUntil(at.toLong())
            assertEquals(before + k * working.size + 1, r.vibrations.size, "working repeat $k starts at $at")
            starts.add(at.toLong())
        }
        assertEquals(3, starts.size)
    }

    @Test
    fun `body timeout - nack body_timeout, the error pattern and the close play, no played`() {
        val r = Rig(bodyTimeoutMs = 5000)
        r.connect(key)
        val a = utt(words = emptyList(), bodyPending = true)
        r.open(a)
        r.sched.drain()
        assertTrue(r.frames.any { it is Nack && it.reason == Reasons.BODY_TIMEOUT })
        assertFalse(r.played().isNotEmpty())
        // the error cue (long-buzz) then the close's declining run are the last buzzes
        val errorCue = spec.pattern(Sequencer.cueFor(spec, Kinds.ERROR)).map { it.buzzMs }
        val close = spec.pattern(Spec.CLOSE_PATTERN).map { it.buzzMs }
        assertEquals(errorCue + close, r.vibrations.takeLast(errorCue.size + close.size))
        assertEquals("idle", r.device.view().phase)
    }

    @Test
    fun `a body that is an error plays the error pattern and nacks with the relay's reason`() {
        val r = Rig()
        r.connect(key)
        val a = utt(words = emptyList(), bodyPending = true)
        r.open(a)
        r.sched.runUntil(r.sched.now + 1000)
        r.device.handleFrame(UtteranceBody(a.id, error = Reasons.COMPOSE_FAILED))
        r.sched.drain()
        assertTrue(r.frames.any { it is Nack && it.id == a.id && it.reason == Reasons.COMPOSE_FAILED })
        assertTrue(r.played().isEmpty())
    }

    @Test
    fun `an utterance arriving mid-utterance is cued between cells, then plays without repeating its cue`() {
        val r = Rig()
        r.connect(key)
        val a = utt(words = listOf("hello", "world"))
        val b = utt(kind = Kinds.REMINDER, words = listOf("pills"))
        r.open(a)
        r.sched.runUntil(r.sched.now + 100)
        r.open(b)
        r.sched.drain()
        val seq = r.frames.drop(1).map { f ->
            val who = when (f) {
                is Progress -> if (f.id == a.id) "a" else "b"
                is Played -> if (f.id == a.id) "a" else "b"
                else -> ""
            }
            "${types(listOf(f))[0]}@$who"
        }
        assertEquals(
            listOf(
                "progress:cue@a",
                "progress:cue@b", // announced at the first boundary, before a's first word
                "progress:word0@a",
                "progress:word1@a",
                "progress:close@a",
                "played@a",
                "progress:word0@b", // b's cue is not repeated at its turn
                "progress:close@b",
                "played@b",
            ),
            seq,
        )
        // the announced cue is the reminder's pattern, spliced between a's segments
        val cueB = spec.pattern(Sequencer.cueFor(spec, Kinds.REMINDER)).map { it.buzzMs }
        val cueA = spec.pattern(Sequencer.cueFor(spec, Kinds.MESSAGE)).map { it.buzzMs }
        assertEquals(cueA + cueB, r.vibrations.take(cueA.size + cueB.size))
    }

    @Test
    fun `advance=tap - the next utterance waits for the wearer, controls and prefs go on the wire`() {
        val r = Rig()
        r.connect(key, Prefs(advance = Advance.TAP))
        val a = utt(words = listOf("one"))
        val b = utt(words = listOf("two"))
        r.open(a)
        r.open(b)
        r.sched.drain()
        assertEquals(1, r.played().size)
        assertEquals("waiting_tap", r.device.view().phase)
        assertEquals(listOf(b.id), r.device.held)
        r.device.control(Controls.ADVANCE)
        assertTrue(r.frames.any { it is Control && it.action == Controls.ADVANCE })
        r.sched.drain()
        assertEquals(2, r.played().size)

        r.device.setPace(300, true)
        assertTrue(r.frames.any { it is PrefChanged && it.prefs.paceMs == 300 })
        assertEquals(300, r.device.prefs.paceMs)
        r.device.setAdvance(Advance.AUTO, true)
        assertTrue(r.frames.any { it is PrefChanged && it.prefs.advance == Advance.AUTO })

        // from the relay: pref.set applies and nothing echoes back
        val n = r.frames.size
        r.device.handleFrame(PrefSet(Prefs(paceMs = 10, advance = Advance.TAP)))
        assertEquals(spec.cellGapMinMs, r.device.prefs.paceMs, "the pace is clamped into the envelope")
        assertEquals(Advance.TAP, r.device.prefs.advance)
        assertEquals(n, r.frames.size)
    }

    @Test
    fun `stop, skip, replay word and replay operate the current utterance`() {
        val r = Rig()
        r.connect(key)
        val a = utt(words = listOf("one", "two", "three"))
        r.open(a)
        r.sched.runUntil(r.sched.now + 800) // into word 0
        r.device.control(Controls.STOP)
        assertEquals(0, r.vibrations.last())
        assertEquals("stopped", r.device.view().phase)
        val n = r.vibrations.size
        r.sched.runUntil(r.sched.now + 5000)
        assertEquals(n, r.vibrations.size, "stopped means silent")
        r.device.control(Controls.SKIP) // resumes at word 1
        assertTrue(r.frames.any { it is Progress && it.phase == Phases.WORD && it.wordIndex == 1 })
        r.device.control(Controls.REPLAY_WORD)
        r.sched.drain()
        assertEquals(1, r.played().size)
        val words = r.frames.filterIsInstance<Progress>().filter { it.phase == Phases.WORD }.map { it.wordIndex }
        assertEquals(listOf(0, 1, 1, 2), words)
        val before = r.frames.size
        r.device.control(Controls.REPLAY) // a local replay of the last played utterance: nothing on the wire but the control
        r.sched.drain()
        assertEquals(listOf("control:replay"), r.since(before))
        assertTrue(r.vibrations.size > n + 5, "the replay played")
    }

    @Test
    fun `an expired utterance is dropped with nack expired unless late is play`() {
        val wall = 1_700_000_000_000L
        val r = Rig(wall = { wall })
        r.connect(key)
        val past = "2020-01-01T00:00:00Z"
        val a = utt(words = listOf("late"), expires = past)
        r.open(a)
        assertEquals(listOf("nack:expired"), r.since(1))
        assertEquals(emptyList(), r.device.held)
        r.device.handleFrame(PrefSet(Prefs(late = Late.PLAY)))
        val b = utt(words = listOf("late"), expires = past)
        r.open(b)
        r.sched.drain()
        assertEquals(1, r.played().count { it.id == b.id })
        assertEquals(1577836800000L, Device.parseWall(past))
        assertEquals(1577836800000L, Device.parseWall("2020-01-01T01:00:00+01:00"))
        assertNull(Device.parseWall("yesterday"))
    }

    @Test
    fun `typed words go out as input text in reply to the last played utterance`() {
        val r = Rig()
        r.connect(key)
        val a = utt(words = listOf("hi"))
        r.open(a)
        r.sched.drain()
        r.device.input(listOf("yes"))
        val f = r.frames.last() as InputText
        assertEquals(listOf("yes"), f.words)
        assertEquals(a.id, f.inReplyTo)
        assertEquals("""{"type":"input.text","words":["yes"],"in_reply_to":"${a.id}"}""", Wire.encode(f))
    }

    @Test
    fun `history is kept in memory only when the preference is on`() {
        val r = Rig()
        r.connect(key)
        r.open(utt(words = listOf("one")))
        r.sched.drain()
        assertEquals(emptyList(), r.device.view().history)
        r.device.setHistory(true, true)
        val b = utt(words = listOf("two"))
        r.open(b)
        r.sched.drain()
        assertEquals(listOf(b.id), r.device.view().history.map { it.id })
        r.device.setHistory(false, true)
        assertEquals(emptyList(), r.device.view().history)
    }
}
