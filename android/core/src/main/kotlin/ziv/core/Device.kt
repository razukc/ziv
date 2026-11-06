/**
 * The device renderer (docs/ARCHITECTURE.md §5.1): a bounded queue of utterances,
 * exactly one playing at a time, the wearer's controls, and the frames that report
 * it all back to the relay. A port of the reference web renderer's state machine
 * (client/src/device.ts), with one substitution: a phone has no "hidden" page, so
 * the refusal here is `muted` — the vibrator is absent (or the wearer has not
 * allowed silent, timing-only playback).
 *
 * Everything time-related goes through the injected clock, timers and player, so
 * the whole state machine runs under a fake clock in the JVM tests.
 *
 * Decisions this class makes that the contract leaves open are marked DECISION.
 */
package ziv.core

import java.time.OffsetDateTime
import java.time.format.DateTimeParseException

const val DEFAULT_QUEUE_CAP = 20
const val DEFAULT_BODY_TIMEOUT_MS = 20_000L
const val HISTORY_CAP = 20

data class DevicePrefs(
    var paceMs: Int,
    var advance: String = Advance.AUTO,
    var late: String = Late.DROP,
    var history: Boolean = false,
)

data class HistoryEntry(val id: String, val kind: String, val label: String?, val words: List<String>, val at: Long)

data class CurrentView(
    val id: String,
    val kind: String,
    val label: String?,
    val words: List<String>,
    val wordIndex: Int?,
    val letterIndex: Int?,
    val bodyPending: Boolean,
)

data class DeviceView(
    /** idle | waiting_tap | stopped | prefix | tail | cue | working | cell | error | close */
    val phase: String,
    val current: CurrentView?,
    /** an arrival cue being announced for a queued utterance */
    val announcing: String?,
    val queueDepth: Int,
    val held: List<String>,
    val lastAcked: String?,
    val prefs: DevicePrefs,
    val history: List<HistoryEntry>,
)

class DeviceDeps(
    val spec: ResolvedSpec,
    val profile: String,
    val player: Player,
    val store: QueueStore,
    val clock: Clock,
    val timers: Timers,
    val send: (UpFrame) -> Unit,
    /** no actuator: the device refuses rather than pretends (`nack muted`) */
    val isMuted: () -> Boolean,
    val wallClock: () -> Long = { System.currentTimeMillis() },
    val log: ((String) -> Unit)? = null,
    val onChange: ((DeviceView) -> Unit)? = null,
    val queueCap: Int = DEFAULT_QUEUE_CAP,
    val bodyTimeoutMs: Long = DEFAULT_BODY_TIMEOUT_MS,
)

class Device(private val d: DeviceDeps) {
    val prefs = DevicePrefs(paceMs = d.spec.cellGapDefaultMs)

    private class Current(val entry: HeldEntry, var segs: List<Segment>, var cursor: Long, val local: Boolean) {
        var idx = 0
        var startedMs: Long? = null
        var stopped = false
        /** nacked already: play the error pattern and the close for the wearer, report nothing more */
        var failed = false
        var workingStartedAt: Long? = null
        var lastWorkingAt: Long? = null
        var workingReported = false
        var waitTimer: Any? = null
    }

    private val queue = ArrayList<HeldEntry>()
    private var lastAcked: String? = null
    private var lastPlayed: HeldEntry? = null
    private var cur: Current? = null
    private var waitingTap = false
    private val pendingCues = ArrayList<HeldEntry>()
    private var announcing: HeldEntry? = null
    private var stepAfterCue = false
    private val historyList = ArrayList<HistoryEntry>()

    // --- lifecycle -------------------------------------------------------------

    /** Load what a previous process held. Cues replay at their turn. */
    fun restore() {
        val snap = d.store.load()
        queue.clear()
        queue.addAll(snap.entries.map { it.copy(cued = false) })
        lastAcked = snap.lastAcked
        emit()
    }

    fun hello(deviceKey: String): Hello = Hello(
        deviceKey = deviceKey,
        profile = d.profile,
        specVersion = d.spec.version,
        paceMs = prefs.paceMs,
        lastAcked = lastAcked,
        held = queue.map { it.utt.id },
    )

    /** Play what is held, if idle and allowed to. */
    fun resume() {
        val head = queue.firstOrNull()
        if (cur == null && !waitingTap && head != null && !d.isMuted()) begin(head, false)
    }

    val held: List<String> get() = queue.map { it.utt.id }

    val lastAckedId: String? get() = lastAcked

    fun view(): DeviceView {
        val cur = this.cur
        var phase = "idle"
        var current: CurrentView? = null
        if (cur != null) {
            val seg = cur.segs.getOrNull(cur.idx)
            phase = if (cur.stopped) "stopped" else (seg?.phase?.wire ?: Phase.CLOSE.wire)
            current = CurrentView(
                id = cur.entry.utt.id,
                kind = cur.entry.utt.kind,
                label = cur.entry.utt.from.label,
                words = wordsOf(cur.entry),
                wordIndex = if (seg?.phase == Phase.CELL) seg.wordIndex else null,
                letterIndex = if (seg?.phase == Phase.CELL) seg.letterIndex else null,
                bodyPending = cur.entry.body == null && cur.entry.utt.bodyPending,
            )
        } else if (waitingTap) {
            phase = "waiting_tap"
        }
        return DeviceView(
            phase = phase,
            current = current,
            announcing = announcing?.utt?.id,
            queueDepth = queue.size,
            held = held,
            lastAcked = lastAcked,
            prefs = prefs.copy(),
            history = historyList.toList(),
        )
    }

    // --- frames from the relay ---------------------------------------------------

    fun handleFrame(f: DownFrame) {
        when (f) {
            is HelloAck -> {
                applyPrefs(f.prefs)
                if (f.specVersion != d.spec.version) {
                    log("relay speaks spec v${f.specVersion}, this device v${d.spec.version}: mismatching utterances will be refused")
                }
                for (u in f.resend) open(u)
                resume()
            }
            is UtteranceOpen -> open(f.utterance)
            is UtteranceBody -> body(f.id, if (f.error != null) BodyState(error = f.error) else BodyState(words = f.words, source = f.source))
            is UtteranceCancel -> cancel(f.id, f.reason)
            is PrefSet -> applyPrefs(f.prefs)
            is Pong -> Unit
            is ProtocolError -> log("relay error: ${f.reason}${if (f.detail.isNotEmpty()) " (${f.detail})" else ""}")
        }
    }

    fun open(utt: Utterance) {
        if (utt.specVersion != d.spec.version) {
            nack(utt.id, Reasons.SPEC_MISMATCH)
            return
        }
        if (d.isMuted()) {
            // DECISION: without an actuator the phone refuses rather than holds; the relay
            // fails over or resends once the device says hello again with a motor.
            nack(utt.id, Reasons.MUTED)
            return
        }
        if (utt.id == lastAcked || queue.any { it.utt.id == utt.id }) {
            log("duplicate ${utt.id} ignored")
            return
        }
        if (queue.size >= d.queueCap) {
            nack(utt.id, Reasons.QUEUE_FULL)
            return
        }
        val entry = HeldEntry(utt = utt, body = null, cued = false, receivedAt = wall())
        queue.add(entry)
        persist()
        val cur = this.cur
        if (cur != null) {
            // announce between cells: at the next segment boundary, or now if the device is silent
            pendingCues.add(entry)
            if (cur.stopped || cur.waitTimer != null) drainCues()
        } else if (waitingTap) {
            pendingCues.add(entry)
            drainCues()
        } else {
            begin(entry, false)
        }
        emit()
    }

    fun body(id: String, state: BodyState) {
        val entry = queue.firstOrNull { it.utt.id == id }
        if (entry == null) {
            log("body for $id, which this device does not hold; ignored")
            return
        }
        entry.body = state
        persist()
        val cur = this.cur
        if (cur != null && cur.entry === entry && cur.waitTimer != null) {
            // waiting in silence between working repeats: go on now
            d.timers.clearTimeout(cur.waitTimer!!)
            cur.waitTimer = null
            step()
        }
        emit()
    }

    fun cancel(id: String, reason: String) {
        pendingCues.removeAll { it.utt.id == id }
        val cur = this.cur
        if (cur != null && cur.entry.utt.id == id) {
            log("current $id cancelled: $reason")
            abandonCurrent()
            removeFromQueue(cur.entry)
            persist()
            afterTurn()
            emit()
            return
        }
        if (announcing?.utt?.id == id) {
            d.player.stop()
            announcing = null
        }
        val i = queue.indexOfFirst { it.utt.id == id }
        if (i >= 0) {
            queue.removeAt(i)
            persist()
        }
        emit()
    }

    fun applyPrefs(p: Prefs) {
        p.paceMs?.let { setPace(it, false) }
        p.advance?.let { setAdvance(it, false) }
        p.late?.let { setLate(it, false) }
        p.history?.let { setHistory(it, false) }
    }

    // --- the wearer -------------------------------------------------------------

    fun setPace(ms: Int, fromWearer: Boolean) {
        val p = d.spec.clampPace(ms)
        if (p != prefs.paceMs) {
            prefs.paceMs = p
            rebuild()
        }
        if (fromWearer) send(PrefChanged(Prefs(paceMs = p)))
        emit()
    }

    fun setAdvance(mode: String, fromWearer: Boolean) {
        prefs.advance = mode
        if (fromWearer) send(PrefChanged(Prefs(advance = mode)))
        if (mode == Advance.AUTO && waitingTap && cur == null) {
            waitingTap = false
            resume()
        }
        emit()
    }

    fun setLate(mode: String, fromWearer: Boolean) {
        prefs.late = mode
        if (fromWearer) send(PrefChanged(Prefs(late = mode)))
        emit()
    }

    fun setHistory(on: Boolean, fromWearer: Boolean) {
        prefs.history = on
        if (!on) historyList.clear()
        if (fromWearer) send(PrefChanged(Prefs(history = on)))
        emit()
    }

    /** Words the wearer typed: an `input.text` frame, in reply to the last played utterance when there is one. */
    fun input(words: List<String>, inReplyTo: String? = lastPlayed?.utt?.id) {
        checkWords(words, "input.text.words")
        if (words.isEmpty()) throw WireException("input.text.words: at least one word")
        send(InputText(words = words, inReplyTo = inReplyTo))
    }

    fun control(action: String) {
        require(action in Controls.ALL) { "unknown control $action" }
        send(Control(action))
        val cur = this.cur
        when (action) {
            Controls.STOP -> {
                if (cur != null) {
                    clearWait(cur)
                    d.player.stop()
                    cur.stopped = true
                } else if (announcing != null) {
                    d.player.stop()
                    announcing = null
                }
            }
            Controls.REPLAY -> {
                if (cur != null) {
                    cur.entry.cued = false // a replay plays the cue again
                    jumpTo(cur, 0)
                } else {
                    lastPlayed?.let { begin(it, true) }
                }
            }
            Controls.REPLAY_WORD -> {
                if (cur != null) {
                    val w = wordAt(cur)
                    if (w != null) jumpTo(cur, firstCellOf(cur.segs, w) ?: cur.idx)
                }
            }
            Controls.SKIP -> {
                if (cur != null && cur.segs.getOrNull(cur.idx)?.phase != Phase.CLOSE) {
                    val w = wordAt(cur)
                    if (w != null) jumpTo(cur, firstCellOf(cur.segs, w + 1) ?: closeOf(cur.segs))
                }
            }
            Controls.ADVANCE -> {
                if (waitingTap && cur == null) {
                    waitingTap = false
                    resume()
                } else if (cur != null) {
                    // DECISION: advancing past an unfinished utterance drops it with a nack,
                    // so the relay never waits out a handoff window on the wearer's choice.
                    abandonCurrent()
                    if (!cur.failed && !cur.local) nack(cur.entry.utt.id, Reasons.CANCELLED_BY_WEARER)
                    removeFromQueue(cur.entry)
                    persist()
                    waitingTap = false
                    resume()
                }
            }
        }
        emit()
    }

    /**
     * The actuator came or went: a muted device stops, refuses what it was playing
     * (`nack muted`) and resumes what it still holds when a motor is back.
     */
    fun onMuted(muted: Boolean) {
        if (muted) {
            pendingCues.clear()
            stepAfterCue = false
            if (announcing != null) {
                d.player.stop()
                announcing = null
            }
            val cur = this.cur
            if (cur != null) {
                abandonCurrent()
                if (!cur.local && !cur.failed) nack(cur.entry.utt.id, Reasons.MUTED)
                removeFromQueue(cur.entry)
                persist()
            }
        } else {
            resume()
        }
        emit()
    }

    // --- playback ---------------------------------------------------------------

    private fun begin(entry: HeldEntry, local: Boolean) {
        waitingTap = false
        if (!local) {
            val exp = parseWall(entry.utt.expires)
            if (exp != null && exp < wall() && prefs.late != Late.PLAY) {
                nack(entry.utt.id, Reasons.EXPIRED)
                removeFromQueue(entry)
                persist()
                afterTurn()
                return
            }
        }
        cur = Current(entry, buildSegs(entry), d.clock.now(), local)
        emit()
        step()
    }

    private fun buildSegs(entry: HeldEntry): List<Segment> {
        val body = entry.body
        val utt = if (body != null && !body.isError) entry.utt.copy(words = body.words, bodyPending = false) else entry.utt
        return Sequencer.segments(utt, d.spec, prefs.paceMs, d.profile)
    }

    /** At a segment boundary: announce waiting cues, then play the next segment. */
    private fun step() {
        val cur = this.cur ?: return
        if (cur.stopped) return
        if (announcing != null) {
            stepAfterCue = true
            return
        }
        if (pendingCues.isNotEmpty()) {
            stepAfterCue = true
            drainCues()
            return
        }
        val seg = cur.segs.getOrNull(cur.idx)
        if (seg == null) {
            finish(cur)
            return
        }
        if (seg.phase == Phase.CUE && cur.entry.cued) {
            // DECISION: announced once already (between another utterance's cells); not repeated at its turn
            cur.idx += 1
            step()
            return
        }
        if (seg.phase == Phase.WORKING) {
            working(cur, seg)
            return
        }
        report(cur, seg)
        playSegment(cur, seg) {
            cur.idx += 1
            step()
        }
    }

    private fun report(cur: Current, seg: Segment) {
        if (cur.failed || cur.local) return
        val id = cur.entry.utt.id
        when {
            seg.phase == Phase.CUE -> {
                cur.entry.cued = true
                send(Progress(id, Phases.CUE))
            }
            seg.phase == Phase.CELL && seg.wordIndex != null && seg.letterIndex == 0 ->
                send(Progress(id, Phases.WORD, seg.wordIndex))
            seg.phase == Phase.CLOSE -> send(Progress(id, Phases.CLOSE))
        }
    }

    private fun playSegment(cur: Current, seg: Segment, done: () -> Unit) {
        val startAt = maxOf(cur.cursor, d.clock.now())
        if (cur.startedMs == null) cur.startedMs = startAt
        emit()
        d.player.play(
            seg.beats,
            PlayOptions(startAt = startAt, totalMs = seg.totalMs, onDone = { endAt ->
                if (this.cur === cur) {
                    cur.cursor = endAt
                    done()
                }
            }),
        )
    }

    private fun working(cur: Current, seg: Segment) {
        if (cur.entry.body != null) {
            applyBody(cur)
            return
        }
        val now = d.clock.now()
        if (cur.workingStartedAt == null) cur.workingStartedAt = maxOf(cur.cursor, now)
        val timeoutAt = cur.workingStartedAt!! + d.bodyTimeoutMs
        if (now >= timeoutAt) {
            fail(cur, Reasons.BODY_TIMEOUT)
            return
        }
        val every = d.spec.workingEveryMs
        val due = cur.lastWorkingAt?.let { it + every } ?: maxOf(cur.cursor, now)
        val wakeAt = minOf(due, timeoutAt)
        if (wakeAt > now + 1) {
            // silence until the next repeat (or the timeout); a body arriving meanwhile cuts the wait
            cur.waitTimer = d.timers.setTimeout(wakeAt - now) {
                cur.waitTimer = null
                step()
            }
            emit()
            return
        }
        cur.lastWorkingAt = if (due >= now - 1) due else now
        cur.cursor = cur.lastWorkingAt!!
        if (!cur.workingReported && !cur.local) {
            cur.workingReported = true
            send(Progress(cur.entry.utt.id, Phases.WORKING))
        }
        playSegment(cur, seg) { step() } // idx stays on `working`; the next step re-decides
    }

    private fun applyBody(cur: Current) {
        val body = cur.entry.body ?: return
        if (body.isError) {
            fail(cur, body.error!!)
            return
        }
        cur.segs = buildSegs(cur.entry)
        val first = cur.segs.indexOfFirst { it.phase == Phase.CELL }
        cur.idx = if (first >= 0) first else closeOf(cur.segs)
        step()
    }

    /** The body never came, or came as an error: tell the relay once, then the error pattern and the close for the wearer. */
    private fun fail(cur: Current, reason: String) {
        if (!cur.failed && !cur.local) nack(cur.entry.utt.id, reason)
        cur.failed = true
        cur.segs = cur.segs.subList(0, minOf(cur.idx, cur.segs.size)) + Sequencer.errorSegments(d.spec)
        step()
    }

    private fun finish(cur: Current) {
        val entry = cur.entry
        clearWait(cur)
        this.cur = null
        if (!cur.failed && !cur.local) {
            send(Played(entry.utt.id, startedMs = maxOf(0L, cur.startedMs ?: cur.cursor), closedMs = maxOf(0L, cur.cursor)))
            lastAcked = entry.utt.id
            lastPlayed = entry
            if (prefs.history) {
                historyList.add(HistoryEntry(entry.utt.id, entry.utt.kind, entry.utt.from.label, wordsOf(entry), wall()))
                while (historyList.size > HISTORY_CAP) historyList.removeAt(0)
            }
        }
        removeFromQueue(entry)
        persist()
        afterTurn()
        emit()
    }

    /** After a close (or a drop): the next utterance starts by itself or waits for the wearer. */
    private fun afterTurn() {
        if (queue.isEmpty() || d.isMuted()) return
        if (prefs.advance == Advance.AUTO) resume() else waitingTap = true
    }

    private fun drainCues() {
        if (announcing != null) return
        val entry = pendingCues.removeFirstOrNull() ?: return
        if (d.isMuted()) return
        announcing = entry
        entry.cued = true
        send(Progress(entry.utt.id, Phases.CUE))
        val seg = Sequencer.cueSegment(d.spec, entry.utt.kind)
        val cur = this.cur
        val now = d.clock.now()
        val startAt = if (cur != null && !cur.stopped && cur.waitTimer == null) maxOf(cur.cursor, now) else now
        emit()
        d.player.play(
            seg.beats,
            PlayOptions(startAt = startAt, totalMs = seg.totalMs, onDone = { endAt ->
                if (announcing === entry) {
                    announcing = null
                    if (this.cur === cur && cur != null && !cur.stopped && cur.waitTimer == null) cur.cursor = endAt
                    if (pendingCues.isNotEmpty()) {
                        drainCues()
                    } else {
                        if (stepAfterCue) {
                            stepAfterCue = false
                            step()
                        }
                        emit()
                    }
                }
            }),
        )
    }

    private fun jumpTo(cur: Current, idx: Int) {
        clearWait(cur)
        d.player.stop()
        cur.idx = idx.coerceIn(0, cur.segs.size)
        cur.cursor = d.clock.now()
        cur.stopped = false
        step()
    }

    private fun rebuild() {
        val cur = this.cur ?: return
        if (cur.failed) return
        val segs = buildSegs(cur.entry)
        // the structure only changes when the body arrives, which applyBody handles
        if (segs.size == cur.segs.size) cur.segs = segs
    }

    private fun abandonCurrent() {
        val cur = this.cur ?: return
        clearWait(cur)
        d.player.stop()
        this.cur = null
        stepAfterCue = false
    }

    private fun clearWait(cur: Current) {
        cur.waitTimer?.let { d.timers.clearTimeout(it) }
        cur.waitTimer = null
    }

    private fun removeFromQueue(entry: HeldEntry) {
        queue.remove(entry)
        pendingCues.removeAll { it === entry }
    }

    private fun persist() {
        val snap = QueueSnapshot(entries = queue.map { it.copy() }, lastAcked = lastAcked)
        try {
            d.store.save(snap)
        } catch (e: Exception) {
            log("queue not persisted: $e")
        }
    }

    private fun nack(id: String, reason: String) = send(Nack(id, reason))

    private fun send(frame: UpFrame) = d.send(frame)

    private fun log(line: String) {
        d.log?.invoke(line)
    }

    private fun wall(): Long = d.wallClock()

    private fun emit() {
        d.onChange?.invoke(view())
    }

    companion object {
        private fun wordsOf(entry: HeldEntry): List<String> {
            val body = entry.body
            return if (body != null && !body.isError) body.words else entry.utt.words
        }

        /** The word the cursor is in, or the last one passed; null before any word. */
        private fun wordAt(cur: Current): Int? {
            var i = minOf(cur.idx, cur.segs.size - 1)
            while (i >= 0) {
                val s = cur.segs[i]
                if (s.phase == Phase.CELL && s.wordIndex != null) return s.wordIndex
                i--
            }
            return null
        }

        private fun firstCellOf(segs: List<Segment>, word: Int): Int? {
            val i = segs.indexOfFirst { it.phase == Phase.CELL && it.wordIndex == word && it.letterIndex == 0 }
            return if (i >= 0) i else null
        }

        private fun closeOf(segs: List<Segment>): Int {
            val i = segs.indexOfFirst { it.phase == Phase.CLOSE }
            return if (i >= 0) i else segs.size
        }

        /** An ISO-8601 instant (the relay writes `...Z` or an offset) as epoch ms; null when absent or unreadable. */
        fun parseWall(text: String?): Long? {
            if (text.isNullOrEmpty()) return null
            return try {
                OffsetDateTime.parse(text).toInstant().toEpochMilli()
            } catch (e: DateTimeParseException) {
                null
            }
        }
    }
}
