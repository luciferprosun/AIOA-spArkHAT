package eu.sparkhat.aioa.companion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class TaskReadbackTest {
    private fun task(state:String="AGENT_RUNNING",id:String="agent-"+ "a".repeat(32)) = buildJsonObject {
        put("task_id",id);put("task_digest","b".repeat(64));put("state",state)
        put("source_sha","c".repeat(40));put("capsule_digest","d".repeat(64));put("mode","OFFLINE_FIXTURE")
        put("receipt",JsonNull)
    }
    @Test fun catalogOrListReadbackCannotRefreshSelectedTask() {
        val t=task()
        val observed=TaskReadbacks().accept(t,agent=true,until=2000,issuedAt=100)
        assertTrue(observed.canStop(t,agent=true,now=1500))
        val afterCatalog=observed.invalidate()
        val connection=Freshness().accept(0,5000,now=2500)
        assertTrue(connection.isFresh(2500))
        assertFalse(afterCatalog.canStop(t,agent=true,now=2500))
        assertFalse(afterCatalog.isFresh(t,agent=true,now=1500))
        val evidence=afterCatalog.accept(t,agent=true,until=5000,issuedAt=102)
        assertTrue(evidence.canStop(t,agent=true,now=2500))
    }
    @Test fun matchingIdAloneCannotBindChangedPayloadOrState() {
        val t=task()
        val proof=TaskReadbacks().accept(t,agent=true,until=2000,issuedAt=100)
        assertFalse(proof.canStop(task("AGENT_APPROVED"),agent=true,now=1500))
        assertFalse(proof.canStop(task(id="agent-"+"e".repeat(32)),agent=true,now=1500))
        assertFalse(proof.canStop(t,agent=false,now=1500))
        assertFalse(proof.canStop(t,agent=true,now=2000))
    }
    @Test fun terminalTaskAndUnknownNeverOfferStop() {
        for (state in listOf("AGENT_COMPLETED","AGENT_UNKNOWN","AGENT_STOPPED","AGENT_FAILED")) {
            val t=task(state)
            assertFalse(state,TaskReadbacks().accept(t,true,2000,100).canStop(t,true,1500))
        }
    }
    @Test fun completionNeedsReceiptAndFixtureIsNotLive() {
        val noReceipt=task("AGENT_COMPLETED")
        assertEquals(CosmicPhase.UNKNOWN,missionPhase(noReceipt))
        val receipt=buildJsonObject { put("kind","fixture");put("verified",false) }
        val done=JsonObject(noReceipt + ("receipt" to receipt))
        assertEquals(CosmicPhase.SUCCEEDED,missionPhase(done))
        assertEquals(CosmicPhase.UNKNOWN,missionPhase(task("unrecognized-success")))
        assertEquals(CosmicPhase.PENDING,missionPhase(task("AGENT_APPROVED")))
    }
    @Test fun boundedHistoryKeepsOnlyMetadataAndOrdersActualObservations() {
        var history=emptyList<UiHistoryEvent>()
        repeat(40) { index -> history=appendUiHistory(history,UiHistoryEvent(UiEventKind.SIGNED_READBACK,index.toLong())) }
        assertEquals(32,history.size)
        assertEquals(8L,history.first().atEpochSeconds)
        assertEquals(39L,history.last().atEpochSeconds)
        assertNull(history.last().taskId)
        val local=UiHistoryEvent(UiEventKind.LOCAL_UNKNOWN,40)
        assertFalse(local.signed)
    }
}
