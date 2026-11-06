/**
 * The protocol side of the socket to the relay, behind a small socket interface so
 * the JVM tests drive it with a fake and the app plugs in OkHttp. `hello` is always
 * the first frame on a socket (the device key travels in it, never in the URL); a
 * reconnect backs off (doubling, capped) and sends a fresh hello built from the
 * device's current `last_acked` and `held`. `ping` on a cadence is liveness only.
 *
 * All callbacks must arrive on the thread the state machine runs on; the socket
 * implementation is responsible for marshalling them there.
 */
package ziv.core

interface SocketListener {
    fun onOpen()
    fun onMessage(text: String)
    /** The socket closed (or failed; a failure reports 1006). Exactly once per socket. */
    fun onClosed(code: Int, detail: String)
}

interface Socket {
    fun send(text: String): Boolean
    fun close()
}

fun interface SocketFactory {
    fun open(url: String, listener: SocketListener): Socket
}

enum class TransportStatus { IDLE, CONNECTING, OPEN, CLOSED }

class TransportDeps(
    val url: String,
    val sockets: SocketFactory,
    val makeHello: () -> Hello,
    val onFrame: (DownFrame) -> Unit,
    val timers: Timers,
    val onStatus: ((TransportStatus, String) -> Unit)? = null,
    /** The socket closed with this code (4401 = the relay refused the device key). Called before any reconnect is scheduled. */
    val onClose: ((Int) -> Unit)? = null,
    val log: ((String) -> Unit)? = null,
    val pingEveryMs: Long = PING_EVERY_MS,
    val backoffInitialMs: Long = 1_000,
    val backoffMaxMs: Long = 30_000,
) {
    companion object {
        const val PING_EVERY_MS = 20_000L
    }
}

class Transport(private val d: TransportDeps) {
    private var socket: Socket? = null
    private var closedByUs = false
    private var backoff = d.backoffInitialMs
    private var reconnectTimer: Any? = null
    private var pingTimer: Any? = null
    private var isOpen = false
    var status: TransportStatus = TransportStatus.IDLE
        private set

    fun connect() {
        closedByUs = false
        open()
    }

    fun close() {
        closedByUs = true
        clearTimers()
        val s = socket
        socket = null
        isOpen = false
        s?.close()
        setStatus(TransportStatus.CLOSED, "closed by the device")
    }

    /**
     * Drop the socket and open a fresh one now, with a fresh hello: the device's way
     * to say "offer me again" after it refused something (a muted phone with its
     * motor back). The old socket's close is ignored; the backoff resets.
     */
    fun reconnect() {
        closedByUs = false
        clearTimers()
        val s = socket
        socket = null
        isOpen = false
        if (s != null) {
            d.log?.invoke("reconnecting with a fresh hello")
            s.close()
        }
        backoff = d.backoffInitialMs
        open()
    }

    /** Send a frame; false (and a log line) when the socket is not open. */
    fun send(frame: UpFrame): Boolean {
        val s = socket
        if (s == null || !isOpen) {
            d.log?.invoke("dropped (not connected): ${Wire.describe(frame)}")
            return false
        }
        val ok = s.send(Wire.encode(frame))
        d.log?.invoke((if (ok) "→ " else "send failed: ") + Wire.describe(frame))
        return ok
    }

    private fun open() {
        setStatus(TransportStatus.CONNECTING, d.url)
        lateinit var s: Socket
        val listener = object : SocketListener {
            override fun onOpen() {
                if (socket !== s) return
                isOpen = true
                backoff = d.backoffInitialMs
                // hello first, before anything else can be sent on this socket
                val hello = d.makeHello()
                s.send(Wire.encode(hello))
                d.log?.invoke("→ ${Wire.describe(hello)}")
                setStatus(TransportStatus.OPEN, d.url)
                schedulePing()
            }

            override fun onMessage(text: String) {
                if (socket !== s) return
                val frame = try {
                    Wire.decodeDown(text)
                } catch (e: WireException) {
                    d.log?.invoke("← unreadable frame: ${e.message}")
                    return
                }
                d.log?.invoke("← ${Wire.describe(frame)}")
                d.onFrame(frame)
            }

            override fun onClosed(code: Int, detail: String) {
                if (socket !== s) return
                socket = null
                isOpen = false
                clearTimers()
                setStatus(TransportStatus.CLOSED, "code $code${if (detail.isNotEmpty()) " $detail" else ""}")
                d.onClose?.invoke(code)
                if (!closedByUs) scheduleReconnect()
            }
        }
        try {
            s = d.sockets.open(d.url, listener)
        } catch (e: Exception) {
            d.log?.invoke("websocket: $e")
            scheduleReconnect()
            return
        }
        socket = s
    }

    private fun schedulePing() {
        pingTimer = d.timers.setTimeout(d.pingEveryMs) {
            pingTimer = null
            if (socket != null && isOpen) {
                send(Ping)
                schedulePing()
            }
        }
    }

    private fun scheduleReconnect() {
        if (closedByUs || reconnectTimer != null) return
        val wait = backoff
        backoff = minOf(d.backoffMaxMs, backoff * 2)
        d.log?.invoke("reconnect in $wait ms")
        reconnectTimer = d.timers.setTimeout(wait) {
            reconnectTimer = null
            if (!closedByUs) open()
        }
    }

    private fun clearTimers() {
        pingTimer?.let { d.timers.clearTimeout(it) }
        pingTimer = null
        reconnectTimer?.let { d.timers.clearTimeout(it) }
        reconnectTimer = null
    }

    private fun setStatus(status: TransportStatus, detail: String) {
        this.status = status
        d.onStatus?.invoke(status, detail)
    }
}

/** `ws://host:port[/prefix][/ws]` or `http://host:port[/prefix]` → the HTTP base and the socket URL. */
data class RelayUrls(val http: String, val ws: String) {
    companion object {
        private val SCHEME = Regex("^([a-zA-Z][a-zA-Z0-9+.-]*)://([^/?#]+)(/[^?#]*)?$")

        fun parse(relay: String): RelayUrls {
            val m = SCHEME.matchEntire(relay.trim()) ?: throw IllegalArgumentException("relay URL must look like ws://host:port or https://host")
            val scheme = m.groupValues[1].lowercase()
            val host = m.groupValues[2]
            val secure = scheme == "wss" || scheme == "https"
            if (!secure && scheme != "ws" && scheme != "http") throw IllegalArgumentException("relay URL: unsupported scheme $scheme")
            val base = m.groupValues[3].replace(Regex("/ws/?$"), "").trimEnd('/')
            return RelayUrls(
                http = "${if (secure) "https" else "http"}://$host$base",
                ws = "${if (secure) "wss" else "ws"}://$host$base/ws",
            )
        }

        /** The host part (no port) of a relay URL, for the plain-HTTP allow-list. */
        fun host(relay: String): String {
            val m = SCHEME.matchEntire(relay.trim()) ?: return ""
            val h = m.groupValues[2]
            return if (h.startsWith("[")) h.substringAfter('[').substringBefore(']') else h.substringBefore(':')
        }
    }
}
