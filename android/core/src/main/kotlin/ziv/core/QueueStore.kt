/**
 * The device's held utterances, persisted so a process restart resumes with `held`
 * ids and `last_acked` in its hello. The snapshot is written whole, so a crash
 * mid-write leaves the previous snapshot intact. The Android app backs this with
 * SQLite; tests use memory.
 */
package ziv.core

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** The body of a `body_pending` utterance once it came: words, or the relay's error reason. */
@Serializable
data class BodyState(
    val words: List<String> = emptyList(),
    val source: String? = null,
    val error: String? = null,
) {
    val isError: Boolean get() = error != null
}

@Serializable
data class HeldEntry(
    val utt: Utterance,
    var body: BodyState? = null,
    /** the arrival cue has been played (announced between another utterance's cells) */
    var cued: Boolean = false,
    /** wall clock, ms since the epoch */
    @SerialName("received_at") val receivedAt: Long = 0,
)

@Serializable
data class QueueSnapshot(
    val entries: List<HeldEntry> = emptyList(),
    @SerialName("last_acked") val lastAcked: String? = null,
)

interface QueueStore {
    val kind: String
    fun load(): QueueSnapshot
    fun save(snap: QueueSnapshot)
}

class MemoryQueueStore : QueueStore {
    override val kind = "memory"
    private var snap = QueueSnapshot()

    override fun load(): QueueSnapshot = copy(snap)

    override fun save(snap: QueueSnapshot) {
        this.snap = copy(snap)
    }

    private fun copy(s: QueueSnapshot): QueueSnapshot =
        QueueSnapshot(s.entries.map { it.copy(body = it.body?.copy(), cued = it.cued) }, s.lastAcked)
}
