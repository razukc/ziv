package ziv.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat

/** After a reboot an enrolled phone comes back on its own: the queue it held is in SQLite, the key in private storage. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        if (!Settings(context).enrolled) return
        ContextCompat.startForegroundService(context, Intent(context, RendererService::class.java).setAction(RendererService.ACTION_START))
    }
}
