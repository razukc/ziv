// The transport over a fake socket: hello first on every socket, frames parsed and
// passed on, ping on the cadence, reconnect with doubling backoff and a fresh hello,
// 4401 reported before any reconnect, close() stays closed.
package ziv.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class TransportTest {
    private class FakeSocket(val url: String, val listener: SocketListener) : Socket {
        val sent = ArrayList<String>()
        var closed = false
        override fun send(text: String): Boolean {
            sent.add(text)
            return true
        }

        override fun close() {
            closed = true
        }
    }

    private class Rig(pingEveryMs: Long = 20_000) {
        val sched = FakeScheduler()
        val sockets = ArrayList<FakeSocket>()
        val frames = ArrayList<DownFrame>()
        val statuses = ArrayList<TransportStatus>()
        val closes = ArrayList<Int>()
        val log = ArrayList<String>()
        var held = listOf<String>()
        var lastAcked: String? = null
        val transport = Transport(
            TransportDeps(
                url = "ws://relay.test/ws",
                sockets = { url, listener -> FakeSocket(url, listener).also { sockets.add(it) } },
                makeHello = { Hello(deviceKey = "k".repeat(32), profile = "single_actuator", specVersion = 4, paceMs = 420, lastAcked = lastAcked, held = held) },
                onFrame = { frames.add(it) },
                timers = sched,
                onStatus = { s, _ -> statuses.add(s) },
                onClose = { closes.add(it) },
                log = { log.add(it) },
                pingEveryMs = pingEveryMs,
            ),
        )
    }

    @Test
    fun `hello is the first frame on the socket and frames are parsed`() {
        val r = Rig()
        r.transport.connect()
        assertEquals(1, r.sockets.size)
        val s = r.sockets[0]
        assertEquals(0, s.sent.size, "nothing before the socket opens")
        s.listener.onOpen()
        assertEquals(1, s.sent.size)
        val hello = Wire.decodeUp(s.sent[0]) as Hello
        assertEquals("single_actuator", hello.profile)
        assertEquals(TransportStatus.OPEN, r.transport.status)
        s.listener.onMessage("""{"type":"hello.ack","v":1,"wearer":"w_1","device":"d_1","spec_version":4,"prefs":{"pace_ms":420}}""")
        assertEquals(1, r.frames.size)
        assertEquals("d_1", (r.frames[0] as HelloAck).device)
        s.listener.onMessage("not json")
        assertEquals(1, r.frames.size)
        assertTrue(r.log.any { it.contains("unreadable frame") })
        assertTrue(r.transport.send(Ping))
        assertEquals("""{"type":"ping"}""", s.sent.last())
    }

    @Test
    fun `ping goes out on the cadence while open`() {
        val r = Rig(pingEveryMs = 20_000)
        r.transport.connect()
        r.sockets[0].listener.onOpen()
        r.sched.runUntil(19_999)
        assertEquals(1, r.sockets[0].sent.size)
        r.sched.runUntil(20_000)
        assertEquals(2, r.sockets[0].sent.size)
        assertTrue(Wire.decodeUp(r.sockets[0].sent[1]) is Ping)
        r.sched.runUntil(40_000)
        assertEquals(3, r.sockets[0].sent.size)
    }

    @Test
    fun `a dropped socket reconnects with doubling backoff and a fresh hello`() {
        val r = Rig()
        r.transport.connect()
        r.sockets[0].listener.onOpen()
        r.lastAcked = "01ACKEDACKED"
        r.held = listOf("01HELDHELD01")
        r.sockets[0].listener.onClosed(1006, "network")
        assertEquals(TransportStatus.CLOSED, r.transport.status)
        assertEquals(listOf(1006), r.closes)
        r.sched.runUntil(999)
        assertEquals(1, r.sockets.size)
        r.sched.runUntil(1000) // the first backoff
        assertEquals(2, r.sockets.size)
        r.sockets[1].listener.onOpen()
        val hello = Wire.decodeUp(r.sockets[1].sent[0]) as Hello
        assertEquals("01ACKEDACKED", hello.lastAcked)
        assertEquals(listOf("01HELDHELD01"), hello.held)
        // an open socket resets the backoff: the next drop waits the initial 1 s again
        r.sockets[1].listener.onClosed(1006, "")
        r.sched.runUntil(r.sched.now + 999)
        assertEquals(2, r.sockets.size)
        r.sched.runUntil(r.sched.now + 1)
        assertEquals(3, r.sockets.size)
        // a socket that never opens doubles the wait: 2 s, then 4 s, capped at 30 s
        r.sockets[2].listener.onClosed(1006, "refused")
        r.sched.runUntil(r.sched.now + 1999)
        assertEquals(3, r.sockets.size)
        r.sched.runUntil(r.sched.now + 1)
        assertEquals(4, r.sockets.size)
        r.sockets[3].listener.onClosed(1006, "refused")
        r.sched.runUntil(r.sched.now + 3999)
        assertEquals(4, r.sockets.size)
        r.sched.runUntil(r.sched.now + 1)
        assertEquals(5, r.sockets.size)
        // a frame from the dead socket is ignored
        r.sockets[0].listener.onMessage("""{"type":"pong"}""")
        assertEquals(0, r.frames.size)
    }

    @Test
    fun `4401 is reported before any reconnect and close stays closed`() {
        val r = Rig()
        r.transport.connect()
        r.sockets[0].listener.onOpen()
        r.sockets[0].listener.onClosed(4401, "unknown device key")
        assertEquals(listOf(4401), r.closes)
        r.transport.close() // the app decides to stop on 4401
        r.sched.runAll()
        assertEquals(1, r.sockets.size, "no reconnect after close()")
        assertFalse(r.transport.send(Ping))
    }

    @Test
    fun `reconnect drops the socket now, resets the backoff and says hello again`() {
        val r = Rig()
        r.transport.connect()
        r.sockets[0].listener.onOpen()
        r.transport.reconnect()
        assertTrue(r.sockets[0].closed)
        assertEquals(2, r.sockets.size)
        r.sockets[0].listener.onClosed(1000, "") // the old socket's close is ignored
        assertEquals(2, r.sockets.size)
        r.sockets[1].listener.onOpen()
        assertTrue(Wire.decodeUp(r.sockets[1].sent[0]) is Hello)
    }

    @Test
    fun `relay URLs resolve to an http base and a socket url`() {
        assertEquals(RelayUrls("http://127.0.0.1:8787", "ws://127.0.0.1:8787/ws"), RelayUrls.parse("ws://127.0.0.1:8787"))
        assertEquals(RelayUrls("http://127.0.0.1:8787", "ws://127.0.0.1:8787/ws"), RelayUrls.parse("http://127.0.0.1:8787/ws"))
        assertEquals(RelayUrls("https://relay.example/ziv", "wss://relay.example/ziv/ws"), RelayUrls.parse("https://relay.example/ziv/"))
        assertEquals("10.0.2.2", RelayUrls.host("http://10.0.2.2:8787"))
        assertEquals("::1", RelayUrls.host("ws://[::1]:8787/ws"))
    }
}
