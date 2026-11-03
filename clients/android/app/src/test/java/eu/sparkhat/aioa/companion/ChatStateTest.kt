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
}
