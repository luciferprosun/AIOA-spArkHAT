package eu.sparkhat.aioa.companion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class CosmicTaskStateTest {
    private fun task(id:String="agent-"+"a".repeat(32),state:String="AGENT_RUNNING")=buildJsonObject {
        put("task_id",id);put("task_digest","b".repeat(64));put("state",state)
        put("source_sha","c".repeat(40));put("capsule_digest","d".repeat(64))
        put("operation",buildJsonObject {put("operation_class","SANDBOX_EXEC")})
        put("receipt",if(state=="AGENT_COMPLETED") buildJsonObject {put("mode","OFFLINE_FIXTURE")} else JsonNull)
    }
    private fun connected()=MissionUi(enrolled=true,freshness=Freshness(1,"FRESH",2000),lastSignedResponseAt=100,
        capabilities=buildJsonObject {put("profile","OFFLINE_FIXTURE");put("stop",true)})

    @Test fun selectedTaskIsBoundToExactRequestedIdentityAndDigest() {
        val t=task();val id=Wire.text(t,"task_id")
        val observed=connected().observeTask(t,true,id)
        assertNull(observed.taskStopReason(true,1500))
        assertThrows(Exception::class.java) {connected().observeTask(t,true,"agent-"+"f".repeat(32))}
        val forged=JsonObject(t+("task_digest" to JsonPrimitive("e".repeat(64))))
        assertThrows(Exception::class.java) {observed.observeTask(forged,true,id)}
        assertThrows(Exception::class.java) {observed.observeTask(t,false,id)}
    }
    @Test fun unrelatedReadbackOrBackgroundCannotRearmStopAndSessionLossKeepsIds() {
        val t=task();val observed=connected().observeTask(t,true,Wire.text(t,"task_id"))
        val invalidated=observed.copy(readbacks=observed.readbacks.invalidate(),freshness=Freshness(2,"FRESH",5000))
        assertEquals(R.string.master_task_readback_required,invalidated.taskStopReason(true,1500))
        assertEquals(R.string.master_task_readback_required,observed.taskStopReason(true,2000))
        val restored=invalidated.copy(lastSignedResponseAt=102).observeTask(t,true,Wire.text(t,"task_id"))
        assertNull(restored.taskStopReason(true,2500))
        val lost=restored.copy(pending="a".repeat(32),pendingAgent="b".repeat(32)).sessionUnavailable()
        assertEquals(R.string.reason_no_session,lost.taskStopReason(true,2500))
        assertEquals(restored.agentTask,lost.agentTask)
        assertFalse(lost.readbacks.isFresh(t,true,2500));assertNotNull(lost.pending);assertNotNull(lost.pendingAgent)
    }
    @Test fun unavailableNativeProfileCannotGainWorkerOrGitControls() {
        val t=task(state="AGENT_COMPLETED")
        val observed=connected().observeTask(t,true,Wire.text(t,"task_id"))
        assertNull(observed.gitPreviewReason(1500))
        val native=observed.copy(capabilities=buildJsonObject {put("profile","NATIVE_STATUS_READ_ONLY_V1");put("stop",false)})
        assertEquals(R.string.cosmic_not_available,native.taskStopReason(true,1500))
        assertEquals(R.string.cosmic_not_available,native.gitPreviewReason(1500))
        assertEquals(R.string.master_task_terminal,observed.taskStopReason(true,1500))
        assertEquals(R.string.master_pending_agent,observed.copy(pendingAgent="e".repeat(32)).gitPreviewReason(1500))
        val changed=JsonObject(t+("state" to JsonPrimitive("AGENT_RUNNING")))
        assertEquals(R.string.master_task_readback_required,observed.copy(agentTask=changed).gitPreviewReason(1500))
    }
    @Test fun unsafeOrUnobservedPayloadNeverCreatesTaskObservation() {
        val t=task()
        assertThrows(Exception::class.java) {connected().copy(lastSignedResponseAt=null).observeTask(t,true)}
        assertThrows(Exception::class.java) {connected().observeTask(task(id="secret-not-a-task-id"),true)}
        val doc=task(id="meta-"+"a".repeat(32),state="PREVIEWED")
        val observed=connected().observeTask(doc,false)
        assertNull(observed.taskStopReason(false,1500))
        assertFalse(observed.readbacks.isFresh(doc,true,1500))
    }
    @Test fun failedSelectionKeepsExactRequestedTaskAndUnrelatedReadCannotReplaceIt() {
        val a=task();val b=task(id="agent-"+"e".repeat(32))
        val selected=connected().observeTask(a,true).requestTask(Wire.text(b,"task_id"),true)
        // Network failure retains A only as history. Details for B must be empty.
        val failed=selected.copy(readbacks=selected.readbacks.invalidate())
        assertNull(failed.detailTask(true))
        assertEquals(Wire.text(b,"task_id"),failed.requestedTask?.id)
        // A different successful read is still A; it does not resolve selection B.
        val catalog=failed.observeTask(a,true)
        assertNull(catalog.detailTask(true))
        assertNotNull(catalog.taskStopReason(true,1500))
        val recovered=catalog.observeTask(b,true,Wire.text(b,"task_id"))
        assertEquals(b,recovered.detailTask(true));assertNull(recovered.taskStopReason(true,1500))
    }
}
