package ziv.android

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager

class ZivApp : Application() {
    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        // Low importance and no vibration: the notification must never buzz the motor the channel speaks on.
        val channel = NotificationChannel(RendererService.CHANNEL, getString(R.string.notification_channel), NotificationManager.IMPORTANCE_LOW).apply {
            description = getString(R.string.notification_channel_description)
            enableVibration(false)
            setSound(null, null)
            setShowBadge(false)
        }
        nm.createNotificationChannel(channel)
    }
}
