/**
 * The wearer's screen: what is happening, the five controls, the preferences, a reply
 * box and (once) the setup. Built for TalkBack and a braille display: every control is
 * labelled, the reading order is the focus order, state changes are announced, and
 * nothing is conveyed by colour alone.
 *
 * On a debug build the launch intent may carry the setup as extras, so an emulator
 * test can do `adb shell am start ... --es relay_url ... --es enroll_code ...`.
 */
package ziv.android

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.widget.SeekBar
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import ziv.android.databinding.ActivityMainBinding
import ziv.core.Advance
import ziv.core.ComposeResult
import ziv.core.Controls
import ziv.core.Words

class MainActivity : AppCompatActivity() {
    private lateinit var b: ActivityMainBinding
    private lateinit var settings: Settings
    private var service: RendererService? = null
    private var lastPhaseText: String? = null
    private var lastStatusText: String? = null
    private var paceSpec: RendererService.SpecInfo? = null
    private var bindingPace = false

    private val listener = RendererService.Listener { state -> render(state) }

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            service = (binder as RendererService.LocalBinder).service.also { it.addListener(listener) }
        }

        override fun onServiceDisconnected(name: ComponentName) {
            service = null
        }
    }

    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (!granted) b.setupResult.text = getString(R.string.notifications_denied)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        settings = Settings(this)
        b = ActivityMainBinding.inflate(layoutInflater)
        setContentView(b.root)
        title = getString(R.string.app_name)

        b.stop.setOnClickListener { service?.control(Controls.STOP) }
        b.replay.setOnClickListener { service?.control(Controls.REPLAY) }
        b.replayWord.setOnClickListener { service?.control(Controls.REPLAY_WORD) }
        b.skip.setOnClickListener { service?.control(Controls.SKIP) }
        b.advance.setOnClickListener { service?.control(Controls.ADVANCE) }

        b.pace.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(seekBar: SeekBar, progress: Int, fromUser: Boolean) {
                val sp = paceSpec ?: return
                val ms = sp.paceMinMs + progress * sp.paceStepMs
                b.paceLabel.text = getString(R.string.pace_label, ms)
                if (fromUser && !bindingPace) service?.setPace(ms)
            }

            override fun onStartTrackingTouch(seekBar: SeekBar) = Unit
            override fun onStopTrackingTouch(seekBar: SeekBar) = Unit
        })
        b.advanceTap.setOnCheckedChangeListener { v, checked -> if (v.isPressed || v.isFocused) service?.setAdvance(if (checked) Advance.TAP else Advance.AUTO) }
        b.silentOk.isChecked = settings.silentOk
        b.silentOk.setOnCheckedChangeListener { v, checked -> if (v.isPressed || v.isFocused) service?.setSilentOk(checked) }

        b.send.setOnClickListener { send() }
        b.connect.setOnClickListener { connectFromForm() }
        b.forget.setOnClickListener {
            service?.forget()
            b.relayUrl.setText("")
            b.enrollCode.setText("")
            b.deviceKey.setText("")
            b.setupResult.text = getString(R.string.status_setup)
        }

        b.relayUrl.setText(settings.relayUrl ?: "")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }

        if (!handleDebugExtras(intent) && settings.enrolled) startRenderer(RendererService.startIntent(this))
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleDebugExtras(intent)
    }

    /** Debug builds accept the setup as launch extras (relay_url, enroll_code or device_key, profile, silent_ok). */
    private fun handleDebugExtras(intent: Intent?): Boolean {
        if (!BuildConfig.DEBUG || intent == null) return false
        val relay = intent.getStringExtra(RendererService.EXTRA_RELAY_URL) ?: return false
        val start = RendererService.startIntent(this).putExtra(RendererService.EXTRA_RELAY_URL, relay)
        intent.getStringExtra(RendererService.EXTRA_ENROLL_CODE)?.let { start.putExtra(RendererService.EXTRA_ENROLL_CODE, it) }
        intent.getStringExtra(RendererService.EXTRA_DEVICE_KEY)?.let { start.putExtra(RendererService.EXTRA_DEVICE_KEY, it) }
        intent.getStringExtra(RendererService.EXTRA_PROFILE)?.let { start.putExtra(RendererService.EXTRA_PROFILE, it) }
        if (intent.hasExtra(RendererService.EXTRA_SILENT_OK)) {
            start.putExtra(RendererService.EXTRA_SILENT_OK, intent.getBooleanExtra(RendererService.EXTRA_SILENT_OK, false))
        }
        b.relayUrl.setText(relay)
        startRenderer(start)
        return true
    }

    private fun startRenderer(intent: Intent) {
        ContextCompat.startForegroundService(this, intent)
    }

    override fun onStart() {
        super.onStart()
        // bound whether or not set up yet, so the setup form can reach the service as soon as it starts
        bindService(Intent(this, RendererService::class.java), connection, Context.BIND_AUTO_CREATE)
    }

    override fun onStop() {
        service?.removeListener(listener)
        service = null
        unbindService(connection)
        super.onStop()
    }

    private fun connectFromForm() {
        val relay = b.relayUrl.text.toString().trim()
        val code = b.enrollCode.text.toString().trim()
        val key = b.deviceKey.text.toString().trim()
        if (relay.isEmpty()) {
            b.setupResult.text = getString(R.string.setup_needs_relay)
            return
        }
        try {
            ziv.core.RelayUrls.parse(relay)
        } catch (e: IllegalArgumentException) {
            b.setupResult.text = getString(R.string.setup_bad_url)
            return
        }
        if (!RelayApi.plainAllowed(relay)) {
            b.setupResult.text = getString(R.string.setup_plain_refused)
            return
        }
        if (code.isEmpty() && key.isEmpty() && settings.deviceKey.isNullOrBlank()) {
            b.setupResult.text = getString(R.string.setup_needs_code)
            return
        }
        val start = RendererService.startIntent(this).putExtra(RendererService.EXTRA_RELAY_URL, relay)
        if (code.isNotEmpty()) start.putExtra(RendererService.EXTRA_ENROLL_CODE, code)
        else if (key.isNotEmpty()) start.putExtra(RendererService.EXTRA_DEVICE_KEY, key)
        b.enrollCode.setText("")
        b.deviceKey.setText("")
        b.setupResult.text = getString(R.string.status_connecting)
        startRenderer(start)
    }

    private fun send() {
        when (val r = Words.compose(b.compose.text.toString())) {
            is ComposeResult.Refused -> {
                b.composeResult.text = r.reason
                b.composeResult.announceForAccessibility(r.reason)
            }
            is ComposeResult.Ok -> {
                val sent = service?.sendInput(r.words) == true
                val text = if (sent) getString(R.string.compose_sent, r.words.joinToString(" ")) else getString(R.string.compose_not_connected)
                if (sent) b.compose.setText("")
                b.composeResult.text = text
                b.composeResult.announceForAccessibility(text)
            }
        }
    }

    private fun render(s: RendererService.State) {
        val statusText = Phrasing.status(this, s)
        if (statusText != lastStatusText) {
            lastStatusText = statusText
            b.status.text = statusText
        }
        val phaseText = Phrasing.phase(this, s)
        if (phaseText != lastPhaseText) {
            lastPhaseText = phaseText
            b.now.text = phaseText
            b.now.announceForAccessibility(phaseText)
        }
        b.queue.text = Phrasing.queue(this, s)
        s.spec?.let { sp ->
            if (paceSpec != sp) {
                paceSpec = sp
                b.pace.max = maxOf(1, (sp.paceMaxMs - sp.paceMinMs) / maxOf(1, sp.paceStepMs))
            }
        }
        s.view?.let { v ->
            paceSpec?.let { sp ->
                val progress = ((v.prefs.paceMs - sp.paceMinMs) / maxOf(1, sp.paceStepMs)).coerceIn(0, b.pace.max)
                if (b.pace.progress != progress) {
                    bindingPace = true
                    b.pace.progress = progress
                    bindingPace = false
                }
                b.paceLabel.text = getString(R.string.pace_label, v.prefs.paceMs)
            }
            val tap = v.prefs.advance == Advance.TAP
            if (b.advanceTap.isChecked != tap) b.advanceTap.isChecked = tap
        }
        val enrolled = s.status != RendererService.Status.SETUP
        b.forget.isEnabled = enrolled || settings.enrolled
        if (s.status == RendererService.Status.SETUP && s.detail.isNotBlank()) b.setupResult.text = s.detail
        else if (s.status == RendererService.Status.OPEN && s.deviceId != null) b.setupResult.text = getString(R.string.enrolled, s.deviceId)
    }
}
