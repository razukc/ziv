// The frames against schema/device-frames-*.json: every up frame this device emits
// uses only keys the schema lists for its type and carries every required one;
// every down frame type parses; what the schema refuses, we refuse.
package ziv.core

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class WireTest {
    private val json = Json { ignoreUnknownKeys = true }

    /** `type` → (properties, required) from a generated frame schema. */
    private fun schemaTypes(name: String): Map<String, Pair<Set<String>, Set<String>>> {
        val root = json.parseToJsonElement(Repo.schemaText(name)).jsonObject
        val defs = root["\$defs"]!!.jsonObject
        val mapping = root["discriminator"]!!.jsonObject["mapping"]!!.jsonObject
        return mapping.entries.associate { (type, ref) ->
            val def = defs[ref.jsonPrimitive.content.substringAfterLast('/')]!!.jsonObject
            val props = def["properties"]!!.jsonObject.keys
            val required = def["required"]?.jsonArray?.map { it.jsonPrimitive.content }?.toSet() ?: emptySet()
            type to (props to required)
        }
    }

    private fun check(schema: Map<String, Pair<Set<String>, Set<String>>>, text: String) {
        val o = json.parseToJsonElement(text).jsonObject
        val type = o["type"]!!.jsonPrimitive.content
        val (props, required) = schema[type] ?: error("schema knows no frame type $type")
        val extra = o.keys - props
        assertTrue(extra.isEmpty(), "$type carries keys the schema lacks: $extra")
        val missing = required - o.keys
        assertTrue(missing.isEmpty(), "$type lacks required keys: $missing")
    }

    @Test
    fun `every up frame we emit fits schema device-frames-up`() {
        val schema = schemaTypes("device-frames-up")
        val frames = listOf(
            Hello(deviceKey = "k".repeat(32), profile = "single_actuator", specVersion = 4, paceMs = 420, lastAcked = null, held = emptyList()),
            Hello(deviceKey = "k".repeat(32), profile = "six_actuator", specVersion = 4, paceMs = null, lastAcked = "01TEST000001", held = listOf("01TEST000002")),
            Progress("01TEST000001", Phases.CUE),
            Progress("01TEST000001", Phases.WORD, 2),
            Played("01TEST000001", 100, 5000),
            Nack("01TEST000001", Reasons.QUEUE_FULL),
            InputText(listOf("yes"), null),
            InputText(listOf("yes", "now"), "01TEST000001"),
            Control(Controls.STOP),
            PrefChanged(Prefs(paceMs = 300)),
            PrefChanged(Prefs(advance = Advance.TAP, late = Late.PLAY, history = false)),
            Ping,
        )
        for (f in frames) check(schema, Wire.encode(f))
        assertEquals(schema.keys, frames.map { json.parseToJsonElement(Wire.encode(it)).jsonObject["type"]!!.jsonPrimitive.content }.toSet(),
            "every up frame type the schema lists is one this device can emit")
    }

    @Test
    fun `exact field names on the wire`() {
        assertEquals(
            """{"type":"hello","v":1,"device_key":"kkkkkkkkkkkkkkkk","profile":"single_actuator","spec_version":4,"pace_ms":420,"held":[]}""",
            Wire.encode(Hello(deviceKey = "k".repeat(16), profile = "single_actuator", specVersion = 4, paceMs = 420)),
        )
        assertEquals("""{"type":"progress","id":"01TEST000001","phase":"word","word_index":0}""", Wire.encode(Progress("01TEST000001", Phases.WORD, 0)))
        assertEquals("""{"type":"played","id":"01TEST000001","started_ms":10,"closed_ms":20}""", Wire.encode(Played("01TEST000001", 10, 20)))
        assertEquals("""{"type":"pref.changed","prefs":{"pace_ms":300}}""", Wire.encode(PrefChanged(Prefs(paceMs = 300))))
    }

    @Test
    fun `every down frame type parses`() {
        val utt = """{"v":1,"id":"01TEST000001","wearer":"w_1","kind":"reminder","from":{"sender":"agent","label":"pills"},
            "prefix":{"mark":"ziv","tail":"triple-pulse"},"words":["meds","nine"],"body_pending":false,"source":"sender",
            "not_before":null,"expires":"2026-11-06T10:00:00Z","spec_version":4}"""
        val ack = Wire.decodeDown("""{"type":"hello.ack","v":1,"wearer":"w_1","device":"d_1","spec_version":4,"prefs":{"pace_ms":420,"advance":"tap"},"resend":[$utt]}""") as HelloAck
        assertEquals(420, ack.prefs.paceMs)
        assertEquals(listOf("meds", "nine"), ack.resend[0].words)
        assertEquals("pills", ack.resend[0].from.label)
        assertEquals("2026-11-06T10:00:00Z", ack.resend[0].expires)
        val open = Wire.decodeDown("""{"type":"utterance.open","utterance":$utt}""") as UtteranceOpen
        assertEquals("ziv", open.utterance.prefix?.mark)
        val body = Wire.decodeDown("""{"type":"utterance.body","id":"01TEST000001","words":["meds"],"source":"echo"}""") as UtteranceBody
        assertEquals("echo", body.source)
        val err = Wire.decodeDown("""{"type":"utterance.body","id":"01TEST000001","error":"compose_failed"}""") as UtteranceBody
        assertEquals("compose_failed", err.error)
        val cancel = Wire.decodeDown("""{"type":"utterance.cancel","id":"01TEST000001","reason":"cancelled_by_sender"}""") as UtteranceCancel
        assertEquals("cancelled_by_sender", cancel.reason)
        val pref = Wire.decodeDown("""{"type":"pref.set","prefs":{"advance":"auto"}}""") as PrefSet
        assertEquals("auto", pref.prefs.advance)
        assertTrue(Wire.decodeDown("""{"type":"pong"}""") is Pong)
        val e = Wire.decodeDown("""{"type":"error","reason":"bad_request","detail":"frame failed validation"}""") as ProtocolError
        assertEquals("bad_request", e.reason)
        // the schema's own frame set is exactly what we parse
        assertEquals(
            setOf("hello.ack", "utterance.open", "utterance.body", "utterance.cancel", "pref.set", "pong", "error"),
            schemaTypes("device-frames-down").keys,
        )
    }

    @Test
    fun `what the schema refuses, we refuse`() {
        assertFailsWith<WireException> { Wire.decodeDown("""{"type":"unknown"}""") }
        assertFailsWith<WireException> { Wire.decodeDown("""not json""") }
        assertFailsWith<WireException> { Wire.decodeDown("""{"type":"utterance.body","id":"01TEST000001","words":["x"],"error":"expired"}""") }
        assertFailsWith<WireException> { Wire.decodeDown("""{"type":"utterance.body","id":"01TEST000001"}""") }
        assertFailsWith<WireException> { Wire.decodeDown("""{"type":"pref.set","prefs":{"advance":"later"}}""") }
        val bad = """{"v":1,"id":"short","wearer":"w_1","kind":"message","from":{"sender":"x"},"words":["hi"],"spec_version":4}"""
        assertFailsWith<WireException> { Wire.decodeUtterance(bad) }
        val noWords = """{"v":1,"id":"01TEST000001","wearer":"w_1","kind":"message","from":{"sender":"x"},"words":[],"spec_version":4}"""
        assertFailsWith<WireException> { Wire.decodeUtterance(noWords) }
        val upper = """{"v":1,"id":"01TEST000001","wearer":"w_1","kind":"message","from":{"sender":"x"},"words":["Hi"],"spec_version":4}"""
        assertFailsWith<WireException> { Wire.decodeUtterance(upper) }
        val kind = """{"v":1,"id":"01TEST000001","wearer":"w_1","kind":"alarm","from":{"sender":"x"},"words":["hi"],"spec_version":4}"""
        assertFailsWith<WireException> { Wire.decodeUtterance(kind) }
    }

    @Test
    fun `the golden utterances all parse`() {
        for ((name, raw) in Repo.goldens()) {
            val u = Wire.decodeUtterance(raw)
            assertTrue(u.id.startsWith("golden-"), name)
            val roundTrip = Wire.decodeUtterance(Wire.encodeUtterance(u))
            assertEquals(u, roundTrip, "$name round-trips")
        }
    }

    @Test
    fun `describe never carries words`() {
        val d = Wire.describe(UtteranceOpen(utt(words = listOf("secret", "words"), prefix = Prefix("ziv", "double-tap"))))
        assertTrue(!d.contains("secret") && d.contains("words=2") && d.contains("prefix=ziv/double-tap"), d)
        val i = Wire.describe(InputText(listOf("secret"), null))
        assertTrue(!i.contains("secret") && i.contains("words=1"), i)
    }

}
