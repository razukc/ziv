/**
 * The wearer's settings and the device credential, in the app's private storage
 * (`MODE_PRIVATE` preferences inside the app sandbox). The device key is shown
 * exactly once by the relay and never leaves this file except in `hello`.
 */
package ziv.android

import android.content.Context
import android.content.SharedPreferences
import java.io.File

class Settings(context: Context) {
    private val prefs: SharedPreferences = context.getSharedPreferences("ziv", Context.MODE_PRIVATE)
    private val specCacheFile = File(context.filesDir, "spec.json")

    var relayUrl: String?
        get() = prefs.getString("relay_url", null)
        set(v) = prefs.edit().putString("relay_url", v).apply()

    var deviceKey: String?
        get() = prefs.getString("device_key", null)
        set(v) = prefs.edit().putString("device_key", v).apply()

    var deviceId: String?
        get() = prefs.getString("device_id", null)
        set(v) = prefs.edit().putString("device_id", v).apply()

    var profile: String
        get() = prefs.getString("profile", DEFAULT_PROFILE) ?: DEFAULT_PROFILE
        set(v) = prefs.edit().putString("profile", v).apply()

    /** The pace the wearer chose; null until a spec default or a relay pref has been applied. */
    var paceMs: Int?
        get() = prefs.getInt("pace_ms", -1).takeIf { it > 0 }
        set(v) = prefs.edit().putInt("pace_ms", v ?: -1).apply()

    var advance: String
        get() = prefs.getString("advance", "auto") ?: "auto"
        set(v) = prefs.edit().putString("advance", v).apply()

    /** Play on the clock even without a vibration motor (emulators, bench phones). Off by default. */
    var silentOk: Boolean
        get() = prefs.getBoolean("silent_ok", false)
        set(v) = prefs.edit().putBoolean("silent_ok", v).apply()

    val enrolled: Boolean get() = !relayUrl.isNullOrBlank() && !deviceKey.isNullOrBlank()

    fun forget() {
        prefs.edit().remove("relay_url").remove("device_key").remove("device_id").apply()
        specCacheFile.delete()
    }

    var cachedSpec: String?
        get() = if (specCacheFile.isFile) specCacheFile.readText() else null
        set(v) {
            if (v == null) specCacheFile.delete() else {
                val tmp = File(specCacheFile.parentFile, "spec.json.tmp")
                tmp.writeText(v)
                tmp.renameTo(specCacheFile)
            }
        }

    companion object {
        const val DEFAULT_PROFILE = "single_actuator"
    }
}
