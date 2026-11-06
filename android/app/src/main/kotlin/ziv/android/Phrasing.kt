/**
 * The words the screen, the notification and TalkBack use for the device's state.
 * Only the current utterance's words ever appear (the word being played), never a
 * history.
 */
package ziv.android

import android.content.Context

object Phrasing {
    fun status(ctx: Context, s: RendererService.State): String = when (s.status) {
        RendererService.Status.SETUP -> if (s.detail.isNotBlank()) s.detail else ctx.getString(R.string.status_setup)
        RendererService.Status.FETCHING_SPEC, RendererService.Status.CONNECTING -> ctx.getString(R.string.status_connecting)
        RendererService.Status.NO_SPEC -> ctx.getString(R.string.status_no_spec)
        RendererService.Status.OPEN -> ctx.getString(R.string.status_open) + if (s.muted) " " + ctx.getString(R.string.status_muted) else ""
        RendererService.Status.CLOSED -> ctx.getString(R.string.status_closed)
        RendererService.Status.REFUSED -> ctx.getString(R.string.status_refused)
    }

    fun phase(ctx: Context, s: RendererService.State): String {
        val v = s.view ?: return ctx.getString(R.string.phase_idle)
        if (v.announcing != null && v.current == null) return ctx.getString(R.string.announcing)
        val cur = v.current ?: return when (v.phase) {
            "waiting_tap" -> ctx.getString(R.string.phase_waiting_tap)
            else -> ctx.getString(R.string.phase_idle)
        }
        val what = when (v.phase) {
            "stopped" -> ctx.getString(R.string.phase_stopped)
            "prefix" -> ctx.getString(R.string.phase_prefix)
            "tail" -> ctx.getString(R.string.phase_tail)
            "cue" -> ctx.getString(R.string.phase_cue)
            "working" -> ctx.getString(R.string.phase_working)
            "cell" -> {
                val wi = cur.wordIndex ?: 0
                ctx.getString(R.string.phase_word, wi + 1, cur.words.size, cur.words.getOrNull(wi) ?: "")
            }
            "error" -> ctx.getString(R.string.phase_error)
            "close" -> ctx.getString(R.string.phase_close)
            else -> v.phase
        }
        val kind = cur.kind.replaceFirstChar { it.uppercase() }
        return if (cur.label != null) ctx.getString(R.string.now_from, kind, cur.label, what) else ctx.getString(R.string.now_kind, kind, what)
    }

    fun queue(ctx: Context, s: RendererService.State): String {
        val depth = s.view?.queueDepth ?: 0
        val waiting = depth - (if (s.view?.current != null) 1 else 0)
        return if (waiting > 0) ctx.getString(R.string.queue_depth, waiting) else ""
    }

    fun notificationText(ctx: Context, s: RendererService.State): String =
        if (s.status == RendererService.Status.OPEN) phase(ctx, s) else status(ctx, s)
}
