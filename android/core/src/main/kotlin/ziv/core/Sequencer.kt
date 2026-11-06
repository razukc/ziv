/**
 * The pure sequencer: (utterance, spec, pace, profile) → a timeline of beats.
 *
 * This is the reference renderer's model (ziv/haptics/reference.py): a beat is one
 * buzz with its start offset, dot mask and duration; silence is the space between
 * beats. Labels follow the reference (`prefix:z`, `tail`, `cue`, `working`,
 * `cell:t`, `close`) so timelines diff line for line.
 *
 * A turn (docs/ARCHITECTURE.md §5.1):
 *
 *     [prefix: mark cells, pace gap between them, breath, the tail pattern]  when present
 *     the kind's cue pattern
 *     [working pattern]                                  once, while body_pending with no words
 *     cells: pace gap inside a word, word gap between words
 *     tail gap, then the close pattern
 *
 * The device plays the same turn segment by segment (one cell or one pattern at a
 * time) so a cue can be announced between cells, the pace can change mid-utterance
 * and the working pattern can repeat on the device's clock; the flattened segments
 * are exactly `timeline()`.
 */
package ziv.core

data class Beat(
    val tMs: Int,
    /** bit n = dot n+1 raised; 0 for whole-device patterns */
    val dotMask: Int,
    val buzzMs: Int,
    val label: String,
) {
    /** One JSONL line in the conformance interchange format, field order as the reference prints it. */
    fun toJsonLine(): String = "{\"t_ms\":$tMs,\"dot_mask\":$dotMask,\"buzz_ms\":$buzzMs,\"label\":\"$label\"}"
}

enum class Phase(val wire: String) {
    PREFIX("prefix"), TAIL("tail"), CUE("cue"), WORKING("working"), CELL("cell"), ERROR("error"), CLOSE("close");
}

data class Segment(
    val phase: Phase,
    val label: String,
    val wordIndex: Int?,
    val letterIndex: Int?,
    val letter: String?,
    /** beats relative to the segment's start */
    val beats: List<Beat>,
    /** from the segment's start to the end of its last buzz */
    val lengthMs: Int,
    /** silence after `lengthMs` before whatever follows */
    val gapAfterMs: Int,
) {
    val totalMs: Int get() = lengthMs + gapAfterMs
}

object Sequencer {
    fun cueFor(spec: ResolvedSpec, kind: String): String =
        (spec.kinds[kind] ?: throw SpecException("spec: no cue for kind \"$kind\"")).cue

    /**
     * The prefix tail: the utterance names a pattern id (ziv/wire.py), but the
     * architecture's example names a kind, so both resolve; anything else falls
     * back to the utterance kind's own tail (the web client's decision, kept).
     */
    fun tailFor(spec: ResolvedSpec, utt: Utterance): String {
        val t = utt.prefix?.tail
        if (t != null && t in spec.patterns) return t
        if (t != null) spec.kinds[t]?.let { return it.tail }
        return (spec.kinds[utt.kind] ?: throw SpecException("spec: no tail for kind \"${utt.kind}\"")).tail
    }

    fun patternSegment(spec: ResolvedSpec, patternId: String, phase: Phase, label: String = phase.wire): Segment {
        val beats = ArrayList<Beat>()
        var t = 0
        var length = 0
        var lastGap = 0
        for (b in spec.pattern(patternId)) {
            beats.add(Beat(t, 0, b.buzzMs, label))
            length = t + b.buzzMs
            t += b.buzzMs + b.gapAfterMs
            lastGap = b.gapAfterMs
        }
        return Segment(phase, label, null, null, null, beats, length, lastGap)
    }

    fun cellSegment(
        spec: ResolvedSpec,
        ch: String,
        enc: Encoding,
        phase: Phase,
        gapAfterMs: Int,
        wordIndex: Int?,
        letterIndex: Int,
    ): Segment {
        val letter = spec.letters[ch] ?: throw SpecException("spec: no cell for \"$ch\"")
        val label = "${phase.wire}:$ch"
        return when (enc) {
            is Encoding.Slots -> {
                // six time slots in `order`: a raised dot is a slot_ms pulse in its slot, an absent dot
                // is slot_ms of silence; slot_gap_ms after every slot but the last; column_gap_ms more
                // after the third. The cell's length is constant whatever the letter.
                val beats = ArrayList<Beat>()
                var t = 0
                val last = enc.order.size - 1
                val columnBreak = enc.order.size / 2 - 1
                enc.order.forEachIndexed { k, dot ->
                    if (dot in letter.dots) beats.add(Beat(t, 1 shl (dot - 1), enc.slotMs, label))
                    t += enc.slotMs
                    if (k < last) t += enc.slotGapMs
                    if (k == columnBreak) t += enc.columnGapMs
                }
                Segment(phase, label, wordIndex, letterIndex, ch, beats, Spec.slotCellMs(enc), gapAfterMs)
            }
            Encoding.Chord -> {
                val ms = spec.cellMs(ch)
                Segment(phase, label, wordIndex, letterIndex, ch, listOf(Beat(0, letter.mask, ms, label)), ms, gapAfterMs)
            }
        }
    }

    /** The whole turn as segments, in playing order. The count does not depend on the pace. */
    fun segments(utt: Utterance, spec: ResolvedSpec, paceMs: Int, profile: String): List<Segment> {
        val pace = spec.clampPace(paceMs)
        val enc = spec.encoding(profile)
        val out = ArrayList<Segment>()
        utt.prefix?.let { prefix ->
            val mark = prefix.mark
            for (i in mark.indices) {
                val last = i == mark.length - 1
                // the breath replaces the last mark cell's gap, before the tail
                out.add(cellSegment(spec, mark[i].toString(), enc, Phase.PREFIX, if (last) spec.prefixBreathMs else pace, null, i))
            }
            out.add(patternSegment(spec, tailFor(spec, utt), Phase.TAIL))
        }
        out.add(patternSegment(spec, cueFor(spec, utt.kind), Phase.CUE))
        val words = utt.words
        if (utt.bodyPending && words.isEmpty()) out.add(patternSegment(spec, Spec.WORKING_PATTERN, Phase.WORKING))
        words.forEachIndexed { wi, w ->
            for (li in w.indices) {
                val lastLetter = li == w.length - 1
                val lastWord = wi == words.size - 1
                // inside a word the pace; between words the word gap; after the last cell the tail gap
                val gap = if (!lastLetter) pace else if (lastWord) spec.tailGapMs else spec.wordGapMs
                out.add(cellSegment(spec, w[li].toString(), enc, Phase.CELL, gap, wi, li))
            }
        }
        out.add(patternSegment(spec, Spec.CLOSE_PATTERN, Phase.CLOSE))
        return out
    }

    /** What plays when the body never came or came as an error: the error cue, then the close. */
    fun errorSegments(spec: ResolvedSpec): List<Segment> = listOf(
        patternSegment(spec, cueFor(spec, Kinds.ERROR), Phase.ERROR),
        patternSegment(spec, Spec.CLOSE_PATTERN, Phase.CLOSE),
    )

    /** The arrival cue on its own, for announcing an utterance that must wait. */
    fun cueSegment(spec: ResolvedSpec, kind: String): Segment = patternSegment(spec, cueFor(spec, kind), Phase.CUE)

    fun flatten(segs: List<Segment>): List<Beat> {
        val out = ArrayList<Beat>()
        var t = 0
        for (s in segs) {
            for (b in s.beats) out.add(Beat(t + b.tMs, b.dotMask, b.buzzMs, b.label))
            t += s.totalMs
        }
        return out
    }

    /** The expected buzzes for `utt` on `profile` at `paceMs` between cells. */
    fun timeline(utt: Utterance, spec: ResolvedSpec, paceMs: Int, profile: String): List<Beat> =
        flatten(segments(utt, spec, paceMs, profile))

    /** First buzz to the end of the close's tail: the time budget. */
    fun durationMs(utt: Utterance, spec: ResolvedSpec, paceMs: Int, profile: String): Int =
        segments(utt, spec, paceMs, profile).sumOf { it.totalMs }

    fun toJsonl(beats: List<Beat>): String = buildString { for (b in beats) append(b.toJsonLine()).append('\n') }
}
