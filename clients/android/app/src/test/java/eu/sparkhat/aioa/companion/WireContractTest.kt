package eu.sparkhat.aioa.companion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** JVM tests to execute on the qualified build host; N1 does not claim execution. */
class WireContractTest {
    @Test fun canonicalPolishUtf8MatchesHost() {
        val v = buildJsonObject { put("z","Zażółć / \n"); put("a",1) }
        assertEquals("{\"a\":1,\"z\":\"Zażółć / \\n\"}",Wire.canonical(v).toString(Charsets.UTF_8))
    }
    @Test fun knownPythonDerSignatureIsAccepted() {
        val raw = javaClass.classLoader!!.getResourceAsStream("mobile_wire_vector.json")!!.bufferedReader().readText()
        val v = Json.parseToJsonElement(raw).jsonObject
        val proof = v.getValue("proof").jsonObject
        assertEquals(Wire.text(v,"canonical_sha256"),Wire.sha(Wire.canonical(proof)))
        Wire.verify(Wire.text(v,"spki"),Wire.text(v,"signature"),proof)
        val changed = JsonObject(proof + ("nonce" to JsonPrimitive("0".repeat(32))))
        assertThrows(Exception::class.java) { Wire.verify(Wire.text(v,"spki"),Wire.text(v,"signature"),changed) }
    }
    @Test fun duplicateKeysFloatsAndOversizeAreRejected() {
        for (raw in listOf("{\"x\":1,\"x\":2}","{\"x\":1.0}","[]","x".repeat(65537))) {
            assertThrows(Exception::class.java) { Wire.parse(raw.toByteArray()) }
        }
    }
    @Test fun unsafeOriginsAreRejected() {
        for (v in listOf("http://example.org","https://u:p@example.org","https://example.org/",
            "https://127.0.0.1","https://example.org:443","https://example.org?q=x")) {
            assertThrows(Exception::class.java) { Wire.origin(v) }
        }
        assertEquals("https://fixture.invalid",Wire.origin("https://fixture.invalid"))
    }
    @Test fun expiredHostProofIsRejected() {
        val p = buildJsonObject { put("issued_at",10); put("expires_at",40) }
        Wire.fresh(p,20)
        assertThrows(Exception::class.java) { Wire.fresh(p,41) }
    }
    @Test fun backgroundResumeDoesNotAcceptLateSuccess() {
        val fresh = Freshness(1,"FRESH")
        val stale = fresh.invalidate("STALE")
        assertEquals("STALE",stale.accept(1).state)
        assertFalse(stale.canStop("RUNNING"))
        assertTrue(stale.accept(2).canStop("RUNNING"))
    }
    @Test fun unknownRemainsUnknownAndCannotStop() {
        assertFalse(Freshness(3,"FRESH").canStop("UNKNOWN"))
        assertFalse(Freshness(3,"UNKNOWN").canStop("RUNNING"))
    }
}
