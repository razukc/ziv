/**
 * The relay's HTTP side as the device uses it: `GET /spec` at connect and
 * `POST /devices/enroll` once, plus the plain-HTTP allow-list. Blocking calls; the
 * service runs them on its own thread.
 */
package ziv.android

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.net.InetAddress
import java.util.concurrent.TimeUnit
import ziv.core.RelayUrls

class RelayApiException(message: String) : RuntimeException(message)

class RelayApi(private val client: OkHttpClient = defaultClient()) {
    private val json = Json { ignoreUnknownKeys = true }

    /** The timing spec verbatim, as the relay serves it. */
    fun fetchSpec(httpBase: String): String {
        val req = Request.Builder().url("$httpBase/spec").get().build()
        client.newCall(req).execute().use { res ->
            if (!res.isSuccessful) throw RelayApiException("GET /spec returned ${res.code}")
            return res.body?.string() ?: throw RelayApiException("GET /spec returned no body")
        }
    }

    data class Enrolled(val device: String, val deviceKey: String)

    /** Exchange a short-lived code for a device key (shown exactly once by the relay). */
    fun enroll(httpBase: String, code: String, profile: String, name: String): Enrolled {
        val body = """{"code":${quote(code)},"profile":${quote(profile)},"name":${quote(name)}}"""
        val req = Request.Builder().url("$httpBase/devices/enroll").post(body.toRequestBody(JSON)).build()
        client.newCall(req).execute().use { res ->
            val text = res.body?.string() ?: ""
            val obj = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull()
            if (!res.isSuccessful) {
                val reason = obj?.get("reason")?.jsonPrimitive?.content ?: "status ${res.code}"
                throw RelayApiException(reason)
            }
            val device = obj?.get("device")?.jsonPrimitive?.content
            val key = obj?.get("device_key")?.jsonPrimitive?.content
            if (device == null || key == null) throw RelayApiException("enroll response lacks device or device_key")
            return Enrolled(device, key)
        }
    }

    private fun quote(s: String): String = json.encodeToString(kotlinx.serialization.serializer<String>(), s)

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()

        fun defaultClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .writeTimeout(15, TimeUnit.SECONDS)
            .build()

        /**
         * Plain `http://`/`ws://` is for the emulator's host (10.0.2.2), loopback and a LAN
         * bench relay on a private range; everything else must be TLS. Decided before any
         * connection is attempted, in every build type (release additionally blocks cleartext
         * at the platform level).
         */
        fun plainAllowed(relayUrl: String): Boolean {
            val urls = RelayUrls.parse(relayUrl)
            if (urls.http.startsWith("https://")) return true
            val host = RelayUrls.host(relayUrl)
            if (host == "10.0.2.2" || host == "localhost") return true
            val addr = runCatching { InetAddress.getByName(host) }.getOrNull() ?: return false
            if (!host.matches(Regex("^[0-9.]+$")) && !host.contains(':')) return false // a name resolving to a private address is still a name
            return addr.isLoopbackAddress || addr.isSiteLocalAddress || addr.isLinkLocalAddress
        }
    }
}
