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
        val fresh = Freshness(1,"FRESH",2000)
        val stale = fresh.invalidate("STALE")
        assertEquals("STALE",stale.accept(1,3000,1000).state)
        assertFalse(stale.canStop("RUNNING",1000))
        assertTrue(stale.accept(2,3000,1000).canStop("RUNNING",1000))
    }
    @Test fun unknownRemainsUnknownAndCannotStop() {
        assertFalse(Freshness(3,"FRESH",2000).canStop("UNKNOWN",1000))
        assertFalse(Freshness(3,"UNKNOWN",2000).canStop("RUNNING",1000))
    }
    @Test fun foregroundProofExpiryDisablesActionsWithoutLifecycleOrRetry() {
        val fresh = Freshness(1,"FRESH",2000)
        assertTrue(fresh.isFresh(1999)); assertFalse(fresh.isFresh(2000))
        assertFalse(fresh.canStop("RUNNING",2000))
        assertFalse(fresh.accept(1,1000,2000).isFresh(2000))
    }
    @Test fun sessionUnavailablePreservesPendingAndEnablesReenrollment() {
        val pending = "a".repeat(32)
        val ui = MissionUi(enrolled=true,pending=pending).sessionUnavailable()
        assertFalse(ui.enrolled); assertEquals(pending,ui.pending)
    }
    @Test fun localArchivePreservesUnresolvedIdAndNeverCreatesCoreSuccess() {
        val pending = "a".repeat(32)
        val archive = PendingHints.archive(pending,listOf("b".repeat(32)))
        assertEquals(listOf("b".repeat(32),pending),archive)
        assertEquals(archive,PendingHints.archive(pending,archive))
        assertThrows(Exception::class.java) { PendingHints.archive("not-an-id",archive) }
    }
    @Test fun agentPendingAndRetainedIdsSurviveUnavailableSession() {
        val pending = "a".repeat(32)
        val retained = listOf("b".repeat(32))
        val ui = MissionUi(enrolled=true,pendingAgent=pending,archivedAgents=retained).sessionUnavailable()
        assertFalse(ui.enrolled)
        assertEquals(pending,ui.pendingAgent); assertEquals(retained,ui.archivedAgents)
        assertEquals(retained+pending,PendingHints.archive(pending,ui.archivedAgents))
    }
    @Test fun agentHandoffCannotLoseIdsWhenArchiveCapacityIsExhausted() {
        val full = (0 until 128).map { it.toString(16).padStart(32,'0') }
        assertEquals(full,PendingHints.archive(full.first(),full))
        assertThrows(Exception::class.java) { PendingHints.archive("f".repeat(32),full) }
        assertEquals(128,full.size)
    }
}
