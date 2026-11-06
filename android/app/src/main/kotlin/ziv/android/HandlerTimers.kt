/**
 * The core's clock and timers on one `Handler`: `uptimeMillis` is the base
 * `postDelayed` schedules against, and the service holds a partial wake lock while
 * anything plays so that clock keeps running with the screen off.
 */
package ziv.android

import android.os.Handler
import android.os.SystemClock
import ziv.core.Clock
import ziv.core.Timers

class HandlerTimers(private val handler: Handler) : Clock, Timers {
    override fun now(): Long = SystemClock.uptimeMillis()

    override fun setTimeout(ms: Long, fn: () -> Unit): Any {
        val r = Runnable { fn() }
        handler.postDelayed(r, maxOf(0L, ms))
        return r
    }

    override fun clearTimeout(handle: Any) {
        (handle as? Runnable)?.let { handler.removeCallbacks(it) }
    }
}
