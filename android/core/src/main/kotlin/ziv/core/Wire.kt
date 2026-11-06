/**
 * The device side of the wire contract. The truth is ziv/wire.py and the JSON
 * Schemas it emits (schema/device-frames-down.json, schema/device-frames-up.json,
 * schema/utterance.json); these classes mirror them field for field, with the
 * exact JSON names. Frames from the relay are parsed structurally; an unknown type
 * or a missing field is a `WireException`, never a silent pass.
 *
 * Reasons stay open strings: the relay may add one and the device must still
 * read the frame.
 */
package ziv.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

class WireException(message: String, cause: Throwable? = null) : RuntimeException(message, cause)

object Reasons {
    const val QUEUE_FULL = "queue_full"
    const val EXPIRED = "expired"
    const val SPEC_MISMATCH = "spec_mismatch"
    const val BODY_TIMEOUT = "body_timeout"
    const val MUTED = "muted"
    const val CANCELLED_BY_WEARER = "cancelled_by_wearer"
    const val CANCELLED_BY_SENDER = "cancelled_by_sender"
    const val COMPOSE_FAILED = "compose_failed"
    const val UNAUTHORIZED = "unauthorized"
    const val BAD_REQUEST = "bad_request"
}

object Kinds {
    const val MESSAGE = "message"
    const val REMINDER = "reminder"
    const val ERROR = "error"
    const val SYSTEM = "system"
    val ALL = listOf(MESSAGE, REMINDER, ERROR, SYSTEM)
}

object Advance {
    const val AUTO = "auto"
    const val TAP = "tap"
}

object Late {
    const val DROP = "drop"
    const val PLAY = "play"
}

object Phases {
    const val CUE = "cue"
    const val WORKING = "working"
    const val WORD = "word"
    const val CLOSE = "close"
}

object Controls {
    const val STOP = "stop"
    const val REPLAY = "replay"
    const val REPLAY_WORD = "replay_word"
    const val SKIP = "skip"
    const val ADVANCE = "advance"
    val ALL = listOf(STOP, REPLAY, REPLAY_WORD, SKIP, ADVANCE)
}

const val WIRE_VERSION = 1
const val MAX_WORDS = 64
const val MAX_WORD_LETTERS = 32
val ID_RE = Regex("^[0-9A-Za-z_-]{8,64}$")
val WORD_RE = Regex("^[a-z]{1,32}$")
val MARK_RE = Regex("^[a-z]{1,8}$")
val PATTERN_ID_RE = Regex("^[a-z][a-z0-9-]{0,31}$")

@Serializable
data class From(val sender: String, val label: String? = null)

/** The name mark and the kind's tail, played before unsolicited content. */
@Serializable
data class Prefix(val mark: String, val tail: String)

/** The wearer's preferences, as they travel on the wire. */
@Serializable
data class Prefs(
    @SerialName("pace_ms") val paceMs: Int? = null,
    val advance: String? = null,
    val late: String? = null,
    val history: Boolean? = null,
)

/** The unit the wearer feels (docs/ARCHITECTURE.md §2). */
@Serializable
data class Utterance(
    val v: Int = 1,
    val id: String,
    val wearer: String,
    val kind: String,
    val from: From,
    val prefix: Prefix? = null,
    val words: List<String> = emptyList(),
    @SerialName("body_pending") val bodyPending: Boolean = false,
    val source: String = "sender",
    @SerialName("not_before") val notBefore: String? = null,
    val expires: String? = null,
    @SerialName("spec_version") val specVersion: Int,
) {
    /** The checks schema/utterance.json makes beyond types; throws `WireException`. */
    fun validated(): Utterance {
        if (v != WIRE_VERSION) throw WireException("utterance.v: not $WIRE_VERSION")
        if (!ID_RE.matches(id)) throw WireException("utterance.id: not an utterance id")
        if (kind !in Kinds.ALL) throw WireException("utterance.kind: unknown kind \"$kind\"")
        prefix?.let {
            if (!MARK_RE.matches(it.mark)) throw WireException("utterance.prefix.mark: not a mark a–z")
            if (!PATTERN_ID_RE.matches(it.tail)) throw WireException("utterance.prefix.tail: not a pattern id")
        }
        checkWords(words, "utterance.words")
        if (!bodyPending && words.isEmpty()) throw WireException("utterance: needs words unless body_pending")
        if (specVersion < 1) throw WireException("utterance.spec_version: not a positive integer")
        return this
    }
}

internal fun checkWords(words: List<String>, what: String) {
    if (words.size > MAX_WORDS) throw WireException("$what: more than $MAX_WORDS words")
    words.forEachIndexed { i, w -> if (!WORD_RE.matches(w)) throw WireException("$what[$i]: not a word a–z") }
}

// --- relay -> device ---------------------------------------------------------

@Serializable
sealed class DownFrame

@Serializable
@SerialName("hello.ack")
data class HelloAck(
    val v: Int = 1,
    val wearer: String,
    val device: String,
    @SerialName("spec_version") val specVersion: Int,
    val prefs: Prefs = Prefs(),
    val resend: List<Utterance> = emptyList(),
) : DownFrame()

@Serializable
@SerialName("utterance.open")
data class UtteranceOpen(val utterance: Utterance) : DownFrame()

/** The words for a `body_pending` utterance — or the reason there are none. */
@Serializable
@SerialName("utterance.body")
data class UtteranceBody(
    val id: String,
    val words: List<String> = emptyList(),
    val source: String = "live",
    val error: String? = null,
) : DownFrame()

@Serializable
@SerialName("utterance.cancel")
data class UtteranceCancel(val id: String, val reason: String) : DownFrame()

@Serializable
@SerialName("pref.set")
data class PrefSet(val prefs: Prefs) : DownFrame()

@Serializable
@SerialName("pong")
data object Pong : DownFrame()

/** A frame the relay could not accept. Never carries message text. */
@Serializable
@SerialName("error")
data class ProtocolError(val reason: String, val detail: String = "") : DownFrame()

// --- device -> relay ---------------------------------------------------------

@Serializable
sealed class UpFrame

/** The first frame on a device socket: the credential travels here, never in a URL. */
@Serializable
@SerialName("hello")
data class Hello(
    val v: Int = 1,
    @SerialName("device_key") val deviceKey: String,
    val profile: String,
    @SerialName("spec_version") val specVersion: Int,
    @SerialName("pace_ms") val paceMs: Int? = null,
    @SerialName("last_acked") val lastAcked: String? = null,
    val held: List<String> = emptyList(),
) : UpFrame()

@Serializable
@SerialName("progress")
data class Progress(
    val id: String,
    val phase: String,
    @SerialName("word_index") val wordIndex: Int? = null,
) : UpFrame()

/** The close finished on the actuator; the device's monotonic clock, in ms. */
@Serializable
@SerialName("played")
data class Played(
    val id: String,
    @SerialName("started_ms") val startedMs: Long,
    @SerialName("closed_ms") val closedMs: Long,
) : UpFrame()

@Serializable
@SerialName("nack")
data class Nack(val id: String, val reason: String) : UpFrame()

/** Words typed on the phone, as a reply or unaddressed. */
@Serializable
@SerialName("input.text")
data class InputText(
    val words: List<String>,
    @SerialName("in_reply_to") val inReplyTo: String? = null,
) : UpFrame()

@Serializable
@SerialName("control")
data class Control(val action: String) : UpFrame()

@Serializable
@SerialName("pref.changed")
data class PrefChanged(val prefs: Prefs) : UpFrame()

@Serializable
@SerialName("ping")
data object Ping : UpFrame()

// --- codec ---------------------------------------------------------------------

object Wire {
    val json: Json = Json {
        classDiscriminator = "type"
        ignoreUnknownKeys = true
        encodeDefaults = true
        explicitNulls = false
        isLenient = false
    }

    fun encode(frame: UpFrame): String = json.encodeToString(UpFrame.serializer(), frame)

    fun encodeUtterance(utt: Utterance): String = json.encodeToString(Utterance.serializer(), utt)

    fun decodeUtterance(text: String): Utterance = try {
        json.decodeFromString(Utterance.serializer(), text).validated()
    } catch (e: SerializationException) {
        throw WireException("utterance: ${e.message}", e)
    } catch (e: IllegalArgumentException) {
        throw WireException("utterance: ${e.message}", e)
    }

    /** Parse one text frame from the relay; every utterance it carries is validated. */
    fun decodeDown(text: String): DownFrame {
        val frame = try {
            json.decodeFromString(DownFrame.serializer(), text)
        } catch (e: SerializationException) {
            throw WireException("frame: ${e.message}", e)
        } catch (e: IllegalArgumentException) {
            throw WireException("frame: ${e.message}", e)
        }
        return when (frame) {
            is HelloAck -> {
                frame.resend.forEach { it.validated() }
                frame.prefs.validated("hello.ack.prefs")
                frame
            }
            is UtteranceOpen -> {
                frame.utterance.validated()
                frame
            }
            is UtteranceBody -> {
                checkWords(frame.words, "utterance.body.words")
                if (!ID_RE.matches(frame.id)) throw WireException("utterance.body.id: not an utterance id")
                if (frame.words.isNotEmpty() == (frame.error != null)) {
                    throw WireException("utterance.body: words or error, exactly one")
                }
                frame
            }
            is UtteranceCancel -> {
                if (!ID_RE.matches(frame.id)) throw WireException("utterance.cancel.id: not an utterance id")
                frame
            }
            is PrefSet -> {
                frame.prefs.validated("pref.set.prefs")
                frame
            }
            is Pong, is ProtocolError -> frame
        }
    }

    /** Parse an up frame (tests and the fake relay read what the device sent). */
    fun decodeUp(text: String): UpFrame = try {
        json.decodeFromString(UpFrame.serializer(), text)
    } catch (e: SerializationException) {
        throw WireException("frame: ${e.message}", e)
    }

    private fun Prefs.validated(what: String) {
        advance?.let { if (it != Advance.AUTO && it != Advance.TAP) throw WireException("$what.advance: not auto|tap") }
        late?.let { if (it != Late.DROP && it != Late.PLAY) throw WireException("$what.late: not drop|play") }
    }

    /** A content-free one-liner for the wire log (never message text). */
    fun describe(frame: UpFrame): String = when (frame) {
        is Hello -> "hello profile=${frame.profile} spec=v${frame.specVersion} pace=${frame.paceMs ?: "-"} " +
            "last_acked=${frame.lastAcked ?: "-"} held=${frame.held.size}"
        is Progress -> "progress id=${frame.id} ${frame.phase}${frame.wordIndex?.let { " $it" } ?: ""}"
        is Played -> "played id=${frame.id} took=${frame.closedMs - frame.startedMs}ms"
        is Nack -> "nack id=${frame.id} reason=${frame.reason}"
        is InputText -> "input.text words=${frame.words.size}${frame.inReplyTo?.let { " in_reply_to=$it" } ?: ""}"
        is Control -> "control ${frame.action}"
        is PrefChanged -> "pref.changed pace=${frame.prefs.paceMs ?: "-"} advance=${frame.prefs.advance ?: "-"}"
        is Ping -> "ping"
    }

    fun describe(frame: DownFrame): String = when (frame) {
        is HelloAck -> "hello.ack wearer=${frame.wearer} device=${frame.device} spec=v${frame.specVersion} resend=${frame.resend.size}"
        is UtteranceOpen -> {
            val u = frame.utterance
            "utterance.open id=${u.id} kind=${u.kind} words=${u.words.size}" +
                (if (u.bodyPending) " body_pending" else "") +
                (u.prefix?.let { " prefix=${it.mark}/${it.tail}" } ?: "")
        }
        is UtteranceBody -> "utterance.body id=${frame.id} " +
            (frame.error?.let { "error=$it" } ?: "words=${frame.words.size}")
        is UtteranceCancel -> "utterance.cancel id=${frame.id} reason=${frame.reason}"
        is PrefSet -> "pref.set pace=${frame.prefs.paceMs ?: "-"} advance=${frame.prefs.advance ?: "-"}"
        is Pong -> "pong"
        is ProtocolError -> "error reason=${frame.reason}${if (frame.detail.isNotEmpty()) " ${frame.detail}" else ""}"
    }
}
