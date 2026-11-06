/**
 * The foreground service that is the device: it owns the socket to the relay, the
 * device state machine, the player and the motor, on one background thread
 * (`ziv-device`), and tells the activity what is happening on the main thread.
 *
 * Start-up: settings → `GET /spec` (cached for the next start) → restore the queue
 * from SQLite → connect with hello first. A reconnect backs off and says hello again
 * with `last_acked` and the held ids. A 4401 means the key is gone; the service stops
 * reconnecting and says so.
 */
package ziv.android

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Binder
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import ziv.core.Device
import ziv.core.DeviceDeps
import ziv.core.DeviceView
import ziv.core.Player
import ziv.core.RelayUrls
import ziv.core.ResolvedSpec
import ziv.core.Spec
import ziv.core.Transport
import ziv.core.TransportDeps
import ziv.core.TransportStatus

class RendererService : Service() {
    enum class Status { SETUP, FETCHING_SPEC, NO_SPEC, CONNECTING, OPEN, CLOSED, REFUSED }

    data class State(
        val status: Status,
        val detail: String,
        val view: DeviceView?,
        val spec: SpecInfo?,
        val muted: Boolean,
        val deviceId: String?,
    )

    data class SpecInfo(val version: Int, val paceMinMs: Int, val paceMaxMs: Int, val paceStepMs: Int, val paceDefaultMs: Int)

    fun interface Listener {
        fun onState(state: State)
    }

    inner class LocalBinder : Binder() {
        val service: RendererService get() = this@RendererService
    }

    private val binder = LocalBinder()
    private lateinit var settings: Settings
    private lateinit var thread: HandlerThread
    private lateinit var handler: Handler
    private lateinit var timers: HandlerTimers
    private lateinit var sink: AndroidVibrateSink
    private lateinit var store: SqliteQueueStore
    private val main = Handler(Looper.getMainLooper())
    private val api = RelayApi()
    private var wakeLock: PowerManager.WakeLock? = null

    // device-thread state
    private var spec: ResolvedSpec? = null
    private var device: Device? = null
    private var transport: Transport? = null
    private var specRetry: Any? = null
    private var status = Status.SETUP
    private var detail = ""
    private var lastNotificationText: String? = null

    // main-thread state
    private val listeners = ArrayList<Listener>()
    @Volatile
    private var lastState: State? = null

    override fun onCreate() {
        super.onCreate()
        settings = Settings(this)
        thread = HandlerThread("ziv-device").also { it.start() }
        handler = Handler(thread.looper)
        timers = HandlerTimers(handler)
        sink = AndroidVibrateSink(this)
        store = SqliteQueueStore(this)
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "ziv:renderer").apply { setReferenceCounted(false) }
        val note = notification(getString(R.string.status_setup))
        when {
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE ->
                startForeground(NOTIFICATION_ID, note, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q ->
                startForeground(NOTIFICATION_ID, note, ServiceInfo.FOREGROUND_SERVICE_TYPE_MANIFEST)
            else -> startForeground(NOTIFICATION_ID, note)
        }
    }

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                handler.post { teardown() }
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_CONTROL -> intent.getStringExtra(EXTRA_ACTION)?.let { control(it) }
            else -> {
                // ACTION_START, or a restart after the process was killed: pick up the saved settings;
                // extras (from the activity, or `adb shell am start` on a debug build) override them.
                val relay = intent?.getStringExtra(EXTRA_RELAY_URL)
                val code = intent?.getStringExtra(EXTRA_ENROLL_CODE)
                val key = intent?.getStringExtra(EXTRA_DEVICE_KEY)
                val profile = intent?.getStringExtra(EXTRA_PROFILE)
                val silent = if (intent?.hasExtra(EXTRA_SILENT_OK) == true) intent.getBooleanExtra(EXTRA_SILENT_OK, false) else null
                handler.post { start(relay, code, key, profile, silent) }
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        handler.post { teardown() }
        thread.quitSafely()
        releaseWake()
        super.onDestroy()
    }

    // --- the activity's view of the service (main thread) -------------------------

    fun addListener(l: Listener) {
        listeners.add(l)
        lastState?.let(l::onState)
    }

    fun removeListener(l: Listener) {
        listeners.remove(l)
    }

    fun control(action: String) = handler.post { device?.control(action) }

    fun setPace(ms: Int) = handler.post {
        device?.setPace(ms, true)
        settings.paceMs = device?.prefs?.paceMs ?: ms
    }

    fun setAdvance(mode: String) = handler.post {
        device?.setAdvance(mode, true)
        settings.advance = mode
    }

    fun setSilentOk(on: Boolean) = handler.post {
        val before = isMuted()
        settings.silentOk = on
        val after = isMuted()
        if (before != after) {
            device?.onMuted(after)
            if (!after) transport?.reconnect() // "offer me again": a fresh hello now that the device can play
        }
        publish()
    }

    /** Words the wearer typed (already normalised by `Words.compose`). Returns false when not connected. */
    fun sendInput(words: List<String>): Boolean {
        if (transport?.status != TransportStatus.OPEN) return false
        handler.post { device?.input(words) }
        return true
    }

    fun forget() = handler.post {
        teardown()
        settings.forget()
        setStatus(Status.SETUP, "")
        publish()
    }

    // --- start-up on the device thread -------------------------------------------------

    private fun start(relay: String?, code: String?, key: String?, profile: String?, silentOk: Boolean?) {
        if (relay != null) settings.relayUrl = relay.trim()
        if (profile != null) settings.profile = profile
        if (silentOk != null) settings.silentOk = silentOk
        if (key != null) {
            settings.deviceKey = key.trim()
            settings.deviceId = null
        }
        val relayUrl = settings.relayUrl
        if (relayUrl.isNullOrBlank()) {
            setStatus(Status.SETUP, "")
            publish()
            return
        }
        val urls = try {
            RelayUrls.parse(relayUrl)
        } catch (e: IllegalArgumentException) {
            setStatus(Status.SETUP, e.message ?: "bad relay url")
            publish()
            return
        }
        if (!RelayApi.plainAllowed(relayUrl)) {
            setStatus(Status.SETUP, getString(R.string.setup_plain_refused))
            publish()
            return
        }
        teardown()
        if (!code.isNullOrBlank()) {
            // enroll first: the code becomes a key, shown once, kept in private storage
            setStatus(Status.CONNECTING, "enrolling")
            publish()
            try {
                val enrolled = api.enroll(urls.http, code.trim().uppercase(), settings.profile, Build.MODEL.take(40).ifBlank { "phone" })
                settings.deviceKey = enrolled.deviceKey
                settings.deviceId = enrolled.device
                Log.i(TAG, "enrolled as ${enrolled.device}")
            } catch (e: Exception) {
                Log.w(TAG, "enroll failed: ${e.message}")
                setStatus(Status.SETUP, getString(R.string.enroll_failed, e.message ?: e.javaClass.simpleName))
                publish()
                return
            }
        }
        if (settings.deviceKey.isNullOrBlank()) {
            setStatus(Status.SETUP, "")
            publish()
            return
        }
        fetchSpecThenConnect(urls)
    }

    private fun fetchSpecThenConnect(urls: RelayUrls) {
        setStatus(Status.FETCHING_SPEC, urls.http)
        publish()
        val fresh = try {
            api.fetchSpec(urls.http)
        } catch (e: Exception) {
            Log.w(TAG, "GET /spec failed: ${e.message}")
            null
        }
        val parsed: ResolvedSpec? = fresh?.let { text ->
            try {
                Spec.parse(text).also { settings.cachedSpec = text }
            } catch (e: Exception) {
                Log.w(TAG, "relay spec unusable: ${e.message}")
                null
            }
        } ?: settings.cachedSpec?.let { cached ->
            try {
                Spec.parse(cached)
            } catch (e: Exception) {
                null
            }
        }
        if (parsed == null) {
            setStatus(Status.NO_SPEC, urls.http)
            publish()
            specRetry = timers.setTimeout(SPEC_RETRY_MS) {
                specRetry = null
                fetchSpecThenConnect(urls)
            }
            return
        }
        spec = parsed
        connect(urls, parsed)
    }

    private fun connect(urls: RelayUrls, spec: ResolvedSpec) {
        val key = settings.deviceKey ?: return
        val player = Player(timers, timers, sink)
        val dev = Device(
            DeviceDeps(
                spec = spec,
                profile = settings.profile,
                player = player,
                store = store,
                clock = timers,
                timers = timers,
                send = { frame -> transport?.send(frame) },
                isMuted = { isMuted() },
                log = { line -> Log.d(TAG, line) },
                onChange = { view -> onViewChanged(view) },
            ),
        )
        dev.restore()
        settings.paceMs?.let { dev.setPace(it, false) }
        dev.setAdvance(settings.advance, false)
        device = dev
        transport = Transport(
            TransportDeps(
                url = urls.ws,
                sockets = OkHttpSockets(handler),
                makeHello = { dev.hello(key) },
                onFrame = { frame -> dev.handleFrame(frame) },
                timers = timers,
                onStatus = { s, d ->
                    when (s) {
                        TransportStatus.CONNECTING -> setStatus(Status.CONNECTING, d)
                        TransportStatus.OPEN -> setStatus(Status.OPEN, d)
                        TransportStatus.CLOSED -> if (status != Status.REFUSED) setStatus(Status.CLOSED, d)
                        TransportStatus.IDLE -> Unit
                    }
                    publish()
                },
                onClose = { code ->
                    if (code == 4401 || code == 4400) {
                        Log.w(TAG, "relay refused this device (close $code); not reconnecting")
                        transport?.close()
                        setStatus(Status.REFUSED, "close $code")
                        publish()
                    }
                },
                log = { line -> Log.d(TAG, line) },
            ),
        )
        transport?.connect()
        publish()
    }

    /** Drop the socket, the device and every pending timer (the device's beats and waits live on this handler). */
    private fun teardown() {
        specRetry = null
        transport?.close()
        transport = null
        device = null
        handler.removeCallbacksAndMessages(null)
        sink.vibrate(0, 0)
        releaseWake()
    }

    private fun isMuted(): Boolean = !sink.present && !settings.silentOk

    private fun onViewChanged(view: DeviceView) {
        val busy = view.phase !in setOf("idle", "waiting_tap", "stopped") || view.announcing != null
        if (busy) acquireWake() else releaseWake()
        // the relay may have set prefs; keep the saved ones in step so a restart's hello carries them
        if (settings.paceMs != view.prefs.paceMs) settings.paceMs = view.prefs.paceMs
        if (settings.advance != view.prefs.advance) settings.advance = view.prefs.advance
        publish(view)
    }

    private fun setStatus(s: Status, d: String) {
        status = s
        detail = d
    }

    private fun publish(view: DeviceView? = device?.view()) {
        val sp = spec
        val state = State(
            status = status,
            detail = detail,
            view = view,
            spec = sp?.let { SpecInfo(it.version, it.cellGapMinMs, it.cellGapMaxMs, it.cellGapStepMs, it.cellGapDefaultMs) },
            muted = isMuted(),
            deviceId = settings.deviceId,
        )
        lastState = state
        val text = Phrasing.notificationText(this, state)
        if (text != lastNotificationText) {
            lastNotificationText = text
            getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(text))
        }
        main.post { for (l in listeners.toList()) l.onState(state) }
    }

    private fun acquireWake() {
        val wl = wakeLock ?: return
        if (!wl.isHeld) wl.acquire(WAKE_LIMIT_MS)
    }

    private fun releaseWake() {
        val wl = wakeLock ?: return
        if (wl.isHeld) wl.release()
    }

    private fun notification(text: String): Notification {
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(text)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .build()
    }

    companion object {
        const val TAG = "ZivRenderer"
        const val CHANNEL = "ziv.renderer"
        const val NOTIFICATION_ID = 1
        const val ACTION_START = "ziv.android.action.START"
        const val ACTION_STOP = "ziv.android.action.STOP"
        const val ACTION_CONTROL = "ziv.android.action.CONTROL"
        const val EXTRA_ACTION = "action"
        const val EXTRA_RELAY_URL = "relay_url"
        const val EXTRA_ENROLL_CODE = "enroll_code"
        const val EXTRA_DEVICE_KEY = "device_key"
        const val EXTRA_PROFILE = "profile"
        const val EXTRA_SILENT_OK = "silent_ok"
        private const val SPEC_RETRY_MS = 5_000L
        /** A safety cap on the wake lock: longer than any utterance the budget admits, short enough to never pin the CPU for good. */
        private const val WAKE_LIMIT_MS = 10 * 60_000L

        fun startIntent(context: Context): Intent = Intent(context, RendererService::class.java).setAction(ACTION_START)
    }
}
