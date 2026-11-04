package eu.sparkhat.aioa.companion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ChatStateTest {
    @Test fun sendRequiresRealSessionCapabilityAndNoUncertainRequest() {
        val state=ChatUi()
        assertFalse(state.canSend(false,true,false,"hello"))
        assertFalse(state.canSend(true,false,false,"hello"))
        assertFalse(state.canSend(true,true,true,"hello"))
        assertTrue(state.canSend(true,true,false,"hello"))
        assertFalse(state.canSend(true,true,false,"😀".repeat(501)))
        val pending=state.start("a".repeat(32))
        assertFalse(pending.canSend(true,true,false,"duplicate"))
        assertEquals("a".repeat(32),pending.uncertain().pendingId)
        assertEquals("UNKNOWN",pending.uncertain().state)
    }
    @Test fun freshSessionNeverAutomaticallyResubmitsOldPaidPrompt() {
        val pending=ChatUi(pendingId="a".repeat(32),state="UNKNOWN")
        assertFalse(pending.canSend(true,true,false,"retry"))
        assertEquals("a".repeat(32),pending.pendingId)
        assertTrue(pending.readbackOnly)
    }
    @Test fun parsingRejectsFakeLiveAndForeignRequest() {
        val value=buildJsonObject {
            put("schema","aioa.mobile.chat-result.v1");put("request_id","a".repeat(32));put("thread_id","b".repeat(32))
            put("device_id","c".repeat(64));put("task_id","chat-"+"a".repeat(32));put("task_digest","d".repeat(64))
            put("request_digest","e".repeat(64));put("source_sha","f".repeat(40));put("capsule_digest","1".repeat(64))
            put("model_id","muse-spark-1.3");put("provider_id","meta_model_api");put("state","SUCCEEDED")
            put("prompt","hello");put("reply","fake");put("receipt",JsonNull);put("save_knowledge",false);put("live_verified",true)
        }
        assertThrows(Exception::class.java) {ChatView.decode(value,"c".repeat(64),"a".repeat(32))}
        assertThrows(Exception::class.java) {ChatView.decode(value,"c".repeat(64),"9".repeat(32))}
    }

    private fun view(id:String,state:String="SUCCEEDED")=ChatView(id,"b".repeat(32),state,"prompt","reply","d".repeat(64),"e".repeat(40),null,null,state=="SUCCEEDED")
    @Test fun restoredCompletedThreadUsesOnlyGetAndShowsLinuxAddedTurn() {
        val restored=ChatUi(threadId="b".repeat(32))
        assertEquals(listOf(ChatReadTarget("THREAD","b".repeat(32))),restored.readbackPlan())
        val updated=restored.acceptThread(listOf(view("a".repeat(32)),view("c".repeat(32))),100)
        assertEquals(2,updated.messages.size);assertNull(updated.pendingId)
        assertEquals("c".repeat(32),updated.messages.last().requestId)
    }
    @Test fun unresolvedRequestRemainsIndependentOfTruncatedThreadHistory() {
        val pending=ChatUi(threadId="b".repeat(32),pendingId="a".repeat(32),state="UNKNOWN")
        assertEquals(listOf(ChatReadTarget("REQUEST","a".repeat(32)),ChatReadTarget("THREAD","b".repeat(32))),pending.readbackPlan())
        val read=pending.acceptThread(listOf(view("c".repeat(32))),100)
        assertEquals("a".repeat(32),read.pendingId);assertTrue(read.readbackOnly)
        val exact=read.accept(view("a".repeat(32)),101)
        assertNull(exact.pendingId)
    }
    @Test fun exactSignedUnadmittedDenialAllowsOnlyANewManualMessage() {
        val id="a".repeat(32);val pending=ChatUi(threadId="b".repeat(32),pendingId=id,state="SENDING")
        val data=buildJsonObject {put("schema","aioa.mobile.chat-error.v1");put("error","CHAT_THREAD_BUSY");put("request_id",id);put("admitted",false)}
        val rejected=ChatUnadmitted.decode(data,id)!!
        assertNull(pending.rejectUnadmitted(rejected).pendingId)
        assertNull(ChatUnadmitted.decode(data,"c".repeat(32)))
        assertNull(ChatUnadmitted.decode(JsonObject(data+("error" to JsonPrimitive("CHAT_REQUEST_CONFLICT"))),id))
        assertNull(ChatUnadmitted.decode(JsonObject(data+("admitted" to JsonPrimitive(true))),id))
        val linuxPending=ChatUi(threadId="b".repeat(32)).acceptThread(listOf(view(id,"PENDING_OWNER")),100)
        assertEquals(id,linuxPending.pendingId)
        assertFalse(linuxPending.canSend(true,true,false,"duplicate"))
    }

    @Test fun separateConversationRequiresAnExactSignedUnknownReadback() {
        val id="a".repeat(32)
        val local=ChatUi(threadId="b".repeat(32),pendingId=id,state="UNKNOWN")
        assertFalse(local.canStartSeparateConversation)
        assertThrows(Exception::class.java) {local.separateConversation()}
        val running=local.accept(view(id,"RUNNING"),100)
        assertFalse(running.canStartSeparateConversation)
        val confirmed=local.accept(view(id,"UNKNOWN"),101)
        assertTrue(confirmed.canStartSeparateConversation)
        assertFalse(confirmed.canSend(true,true,false,"retry"))
        val separate=confirmed.separateConversation()
        assertNull(separate.pendingId);assertNull(separate.threadId)
        assertTrue(separate.messages.isEmpty())
        assertEquals(setOf(id),separate.unresolvedRequestIds)
        assertTrue(separate.readbackPlan().isEmpty())
        assertTrue(separate.canSend(true,true,false,"a separate manually written message"))
        assertEquals("UNKNOWN",confirmed.messages.single().state)
    }

    @Test fun separateConversationRetainsPublicUnknownIdsAcrossRestartAndNewSend() {
        val old="c".repeat(32);val id="a".repeat(32)
        val confirmed=ChatUi(threadId="b".repeat(32),pendingId=id,
            unresolvedRequestIds=setOf(old)).accept(view(id,"UNKNOWN"),100)
        val separate=confirmed.separateConversation()
        val restored=ChatUi(unresolvedRequestIds=separate.unresolvedRequestIds)
        assertEquals(setOf(old,id),restored.unresolvedRequestIds)
        assertTrue(restored.readbackPlan().isEmpty())
        val next=restored.start("d".repeat(32))
        assertEquals("d".repeat(32),next.pendingId)
        assertEquals(setOf(old,id),next.unresolvedRequestIds)
    }

    @Test fun malformedOrExcessiveUnresolvedIdsFailClosed() {
        assertThrows(Exception::class.java) {ChatUi(unresolvedRequestIds=setOf("not-an-id"))}
        val tooMany=(0..128).map {it.toString(16).padStart(32,'0')}.toSet()
        assertThrows(Exception::class.java) {ChatUi(unresolvedRequestIds=tooMany)}
        assertFalse(ChatUi(state="UNKNOWN",error="CHAT_LOCAL_HISTORY_INVALID").canSend(true,true,false,"message"))
    }
}
