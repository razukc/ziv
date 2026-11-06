/**
 * OkHttp WebSockets behind the core's `SocketFactory`, with every callback marshalled
 * onto the device thread's handler so the state machine is single-threaded.
 */
package ziv.android

import android.os.Handler
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import java.util.concurrent.TimeUnit
import ziv.core.Socket
import ziv.core.SocketFactory
import ziv.core.SocketListener

class OkHttpSockets(private val handler: Handler, private val client: OkHttpClient = defaultClient()) : SocketFactory {
    override fun open(url: String, listener: SocketListener): Socket {
        var closedReported = false
        fun reportClosed(code: Int, detail: String) {
            handler.post {
                if (!closedReported) {
                    closedReported = true
                    listener.onClosed(code, detail)
                }
            }
        }
        val ws = client.newWebSocket(
            Request.Builder().url(url).build(),
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    handler.post { listener.onOpen() }
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    handler.post { listener.onMessage(text) }
                }

                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    webSocket.close(code, null)
                    reportClosed(code, reason)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    reportClosed(code, reason)
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    reportClosed(1006, t.message ?: t.javaClass.simpleName)
                }
            },
        )
        return object : Socket {
            override fun send(text: String): Boolean = ws.send(text)
            override fun close() {
                ws.close(1000, "device closing")
            }
        }
    }

    companion object {
        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS) // a websocket reads forever; liveness is the protocol's ping
            .build()
    }
}
