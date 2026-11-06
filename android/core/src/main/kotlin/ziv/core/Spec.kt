/**
 * The timing spec as the relay serves it (`GET /spec`, i.e. docs/haptic-timing.json
 * verbatim), resolved into the view every duration in this renderer is derived from.
 *
 * Nothing in this package carries a millisecond of its own: a slot width, a word
 * gap, a pattern's beats or the pace envelope only ever come from the spec that was
 * parsed here. Spec v4 is required — `kinds`, `profiles`, `constants.word_gap_ms`
 * and `constants.working_every_ms` must be present — because inventing a fallback
 * number would be a literal by another name (DECISION: the web client's v3 fallbacks
 * are not ported; the relay serves v4).
 */
package ziv.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonPrimitive

class SpecException(message: String) : RuntimeException(message)

data class SpecBeat(val buzzMs: Int, val gapAfterMs: Int)

data class KindSpec(val cue: String, val tail: String)

/** How a profile encodes a cell. */
sealed interface Encoding {
    /** The band: the raised dots driven together for the cell's duration. */
    data object Chord : Encoding

    /** A phone: one motor, a cell is six time slots in `order`. */
    data class Slots(val slotMs: Int, val slotGapMs: Int, val columnGapMs: Int, val order: List<Int>) : Encoding
}

data class Letter(val dots: List<Int>, val count: Int, val mask: Int)

class ResolvedSpec(
    val version: Int,
    val cellBaseMs: Int,
    val cellPerDotMs: Int,
    val cellGapDefaultMs: Int,
    val cellGapMinMs: Int,
    val cellGapMaxMs: Int,
    val cellGapStepMs: Int,
    val tailGapMs: Int,
    val prefixBreathMs: Int,
    val wordGapMs: Int,
    val workingEveryMs: Int,
    val conformanceToleranceMs: Int?,
    val letters: Map<String, Letter>,
    val patterns: Map<String, List<SpecBeat>>,
    val kinds: Map<String, KindSpec>,
    val profiles: Map<String, Encoding>,
    val prefixMark: String?,
) {
    /** Chord cell duration: `cell_base_ms + cell_per_dot_ms × dots`. */
    fun cellMs(ch: String): Int {
        val letter = letters[ch] ?: throw SpecException("spec: no cell for \"$ch\"")
        return cellBaseMs + cellPerDotMs * letter.count
    }

    fun clampPace(paceMs: Int): Int = paceMs.coerceIn(cellGapMinMs, cellGapMaxMs)

    fun pattern(id: String): List<SpecBeat> =
        patterns[id] ?: throw SpecException("spec: no attention pattern \"$id\"")

    fun encoding(profile: String): Encoding =
        profiles[profile] ?: throw SpecException("spec: no profile $profile")

    /** How long one play of a pattern takes, its final gap included. */
    fun patternMs(id: String): Int = pattern(id).sumOf { it.buzzMs + it.gapAfterMs }
}

object Spec {
    const val CLOSE_PATTERN = "end-of-message"
    const val WORKING_PATTERN = "processing"
    const val SLOT_COUNT = 6
    val PROFILE_NAMES = listOf("six_actuator", "single_actuator")

    private val json = Json { ignoreUnknownKeys = true; isLenient = false }

    fun parse(text: String): ResolvedSpec = resolve(json.parseToJsonElement(text))

    fun maskOf(dots: Iterable<Int>): Int = dots.fold(0) { m, d -> m or (1 shl (d - 1)) }

    /** Fixed duration of a slot cell: every slot, every slot gap but the last, the column break. */
    fun slotCellMs(enc: Encoding.Slots): Int =
        SLOT_COUNT * enc.slotMs + (SLOT_COUNT - 1) * enc.slotGapMs + enc.columnGapMs

    private fun obj(v: JsonElement?, what: String): JsonObject =
        (v as? JsonObject) ?: throw SpecException("spec: $what must be an object")

    private fun posInt(v: JsonElement?, what: String): Int {
        val n = (v as? JsonPrimitive)?.takeIf { !it.isString }?.intOrNull
        if (n == null || n < 0) throw SpecException("spec: $what must be a non-negative integer")
        return n
    }

    private fun optInt(v: JsonElement?): Int? =
        (v as? JsonPrimitive)?.takeIf { !it.isString }?.intOrNull?.takeIf { it >= 0 }

    private fun str(v: JsonElement?): String? = (v as? JsonPrimitive)?.takeIf { it.isString }?.content

    private fun parseEncoding(v: JsonElement?, pid: String): Encoding {
        val o = obj(v, "profiles.$pid")
        return when (val enc = str(o["encoding"])) {
            "slots" -> {
                val orderRaw = o["order"] ?: throw SpecException("spec: profiles.$pid.order is required")
                val order = (orderRaw as? JsonArray)?.map { it.jsonPrimitive.intOrNull ?: -1 }
                    ?: throw SpecException("spec: profiles.$pid.order must be a list")
                if (order.size != SLOT_COUNT || order.toSet().size != SLOT_COUNT || order.any { it < 1 || it > SLOT_COUNT }) {
                    throw SpecException("spec: profiles.$pid.order must list dots 1–6 once each")
                }
                Encoding.Slots(
                    slotMs = posInt(o["slot_ms"], "profiles.$pid.slot_ms"),
                    slotGapMs = posInt(o["slot_gap_ms"], "profiles.$pid.slot_gap_ms"),
                    columnGapMs = posInt(o["column_gap_ms"], "profiles.$pid.column_gap_ms"),
                    order = order,
                )
            }
            "chord", null -> Encoding.Chord
            else -> throw SpecException("spec: profiles.$pid.encoding=\"$enc\" is not chord or slots")
        }
    }

    /** Validate a raw spec and derive the view the sequencer works from. */
    fun resolve(raw: JsonElement): ResolvedSpec {
        val s = obj(raw, "spec")
        val version = posInt(s["version"], "version")
        val c = obj(s["constants"], "constants")
        val ui = (s["ui"] as? JsonObject) ?: JsonObject(emptyMap())

        val counts = obj(s["letters"], "letters")
        val pats = obj(s["letter_patterns"], "letter_patterns")
        val letters = LinkedHashMap<String, Letter>()
        for ((ch, dotsRaw) in pats) {
            val dots = (dotsRaw as? JsonArray)?.map { it.jsonPrimitive.intOrNull ?: -1 }?.sorted()
                ?: throw SpecException("spec: letter_patterns.$ch must be a list")
            if (dots.any { it < 1 || it > SLOT_COUNT }) throw SpecException("spec: letter_patterns.$ch must list dots 1–6")
            val declared = optInt(counts[ch])
            if (declared != dots.size) {
                throw SpecException("spec: letters.$ch=$declared disagrees with letter_patterns.$ch (${dots.size} dots)")
            }
            letters[ch] = Letter(dots, dots.size, maskOf(dots))
        }
        if (letters.isEmpty()) throw SpecException("spec: letter_patterns is empty")

        val ap = (s["attention_patterns"] as? JsonArray) ?: throw SpecException("spec: attention_patterns must be a list")
        val patterns = LinkedHashMap<String, List<SpecBeat>>()
        for (p in ap) {
            val po = obj(p, "attention_patterns[]")
            val id = str(po["id"])?.takeIf { it.isNotEmpty() }
                ?: throw SpecException("spec: attention_patterns[].id must be a string")
            val beatsRaw = (po["beats"] as? JsonArray)?.takeIf { it.isNotEmpty() }
                ?: throw SpecException("spec: attention_patterns $id has no beats")
            patterns[id] = beatsRaw.mapIndexed { i, b ->
                val bo = obj(b, "attention_patterns $id beat $i")
                SpecBeat(
                    buzzMs = posInt(bo["buzz_ms"], "attention_patterns $id beat $i buzz_ms"),
                    gapAfterMs = posInt(bo["gap_after_ms"], "attention_patterns $id beat $i gap_after_ms"),
                )
            }
        }
        for (need in listOf(CLOSE_PATTERN, WORKING_PATTERN)) {
            if (need !in patterns) throw SpecException("spec: attention_patterns lacks $need")
        }

        val prefix = (s["prefix"] as? JsonObject) ?: JsonObject(emptyMap())
        val prefixMark = str(prefix["mark"])

        val kindsRaw = (s["kinds"] as? JsonObject)?.takeIf { it.isNotEmpty() }
            ?: throw SpecException("spec: kinds is required (spec v4)")
        val kinds = LinkedHashMap<String, KindSpec>()
        for ((k, v) in kindsRaw) {
            val ko = obj(v, "kinds.$k")
            val cue = str(ko["cue"])?.takeIf { it in patterns } ?: throw SpecException("spec: kinds.$k.cue names no pattern")
            val tail = str(ko["tail"])?.takeIf { it in patterns } ?: throw SpecException("spec: kinds.$k.tail names no pattern")
            kinds[k] = KindSpec(cue, tail)
        }

        val profilesRaw = (s["profiles"] as? JsonObject)?.takeIf { it.isNotEmpty() }
            ?: throw SpecException("spec: profiles is required (spec v4)")
        val profiles = LinkedHashMap<String, Encoding>()
        for ((pid, pv) in profilesRaw) profiles[pid] = parseEncoding(pv, pid)
        for (need in PROFILE_NAMES) {
            if (need !in profiles) throw SpecException("spec: profiles lacks $need")
        }

        val minGap = posInt(c["cell_gap_min_ms"], "constants.cell_gap_min_ms")
        val maxGap = posInt(c["cell_gap_max_ms"], "constants.cell_gap_max_ms")
        if (minGap > maxGap) throw SpecException("spec: cell_gap_min_ms exceeds cell_gap_max_ms")
        val defaultGap = posInt(c["cell_gap_default_ms"], "constants.cell_gap_default_ms").coerceIn(minGap, maxGap)

        return ResolvedSpec(
            version = version,
            cellBaseMs = posInt(c["cell_base_ms"], "constants.cell_base_ms"),
            cellPerDotMs = posInt(c["cell_per_dot_ms"], "constants.cell_per_dot_ms"),
            cellGapDefaultMs = defaultGap,
            cellGapMinMs = minGap,
            cellGapMaxMs = maxGap,
            cellGapStepMs = posInt(ui["cell_gap_step_ms"], "ui.cell_gap_step_ms"),
            tailGapMs = posInt(c["tail_gap_ms"], "constants.tail_gap_ms"),
            prefixBreathMs = posInt(c["prefix_breath_ms"], "constants.prefix_breath_ms"),
            wordGapMs = posInt(c["word_gap_ms"], "constants.word_gap_ms (spec v4)"),
            workingEveryMs = posInt(c["working_every_ms"], "constants.working_every_ms (spec v4)"),
            conformanceToleranceMs = optInt(c["conformance_tolerance_ms"]),
            letters = letters,
            patterns = patterns,
            kinds = kinds,
            profiles = profiles,
            prefixMark = prefixMark,
        )
    }
}
