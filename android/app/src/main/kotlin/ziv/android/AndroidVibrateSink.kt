/**
 * The phone's one motor as the core's `VibrateSink`. A beat is one waveform — silence 0,
 * then `ms` at full amplitude — when the motor has amplitude control, else a one-shot;
 * `vibrate(_, 0)` cancels. The dot mask is ignored: on `single_actuator` the letter
 * lives in where the pulses fall, not in which motor. Vibrations are tagged as
 * accessibility usage so Do Not Disturb and "touch feedback" settings do not silence
 * the channel.
 */
package ziv.android

import android.content.Context
import android.media.AudioAttributes
import android.os.Build
import android.os.VibrationAttributes
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import ziv.core.VibrateSink

class AndroidVibrateSink(context: Context) : VibrateSink {
    private val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
        (context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager)?.defaultVibrator
    } else {
        @Suppress("DEPRECATION")
        context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
    }

    val present: Boolean get() = vibrator?.hasVibrator() == true
    val amplitudeControl: Boolean get() = vibrator?.hasAmplitudeControl() == true

    private val legacyAttributes: AudioAttributes = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
        .build()

    override fun vibrate(dotMask: Int, ms: Int) {
        val v = vibrator ?: return
        if (ms <= 0) {
            v.cancel()
            return
        }
        val effect = if (v.hasAmplitudeControl()) {
            VibrationEffect.createWaveform(longArrayOf(0L, ms.toLong()), intArrayOf(0, FULL_AMPLITUDE), -1)
        } else {
            VibrationEffect.createOneShot(ms.toLong(), VibrationEffect.DEFAULT_AMPLITUDE)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            v.vibrate(effect, VibrationAttributes.createForUsage(VibrationAttributes.USAGE_ACCESSIBILITY))
        } else {
            @Suppress("DEPRECATION")
            v.vibrate(effect, legacyAttributes)
        }
    }

    companion object {
        /** The platform's amplitude scale is 1..255 (VibrationEffect); a buzz is always at the top of it. */
        private const val FULL_AMPLITUDE = 255
    }
}
