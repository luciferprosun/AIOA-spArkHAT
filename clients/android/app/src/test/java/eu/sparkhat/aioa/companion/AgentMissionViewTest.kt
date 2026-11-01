package eu.sparkhat.aioa.companion

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Source tests for the qualified JDK/SDK host; never reported as run offline. */
class AgentMissionViewTest {
    private val source = "1".repeat(40)
    private val capsule = "a".repeat(64)
    private val scope = "b".repeat(64)
    private fun pending() = buildJsonObject {
        put("schema","aioa.mobile.mission-view.v2"); put("task_id","agent-"+"c".repeat(32))
        put("task_digest","d".repeat(64)); put("source_sha",source); put("capsule_digest",capsule)
        put("owner_scope_digest",scope); put("owner_authority","NOT_BOUND")
        put("state","AGENT_PENDING"); put("mode","OFFLINE_FIXTURE")
        put("provider_id","meta_model_api"); put("model_id","muse-spark-1.3")
        put("live_verified",false); put("verified",false); put("can_run",false)
        put("permissions",buildJsonObject {
            for (key in listOf("run","approve","native_execute","install","github_write","meta_spend")) put(key,false)
        })
        put("files",buildJsonObject {}); put("diff",buildJsonObject {})
        put("steps",buildJsonArray {}); put("tests",buildJsonObject { put("status","NOT_RUN"); put("passed",0) })
        put("install_plan",buildJsonObject {}); put("git",buildJsonObject {})
        put("operation",buildJsonObject { put("operation_class","SANDBOX_EXEC") })
        put("receipt",JsonNull)
    }
    @Test fun pendingIsTypedAndCannotGrantOwnerAuthority() {
        val view = AgentMissionView.decode(pending(),source,capsule,scope)
        assertEquals(AgentState.AGENT_PENDING,view.state)
        assertTrue(view.needsHostApproval)
    }
    @Test fun forgedNativePermissionAndProviderAreRejected() {
        val p = pending()
        val permissions = p.getValue("permissions").jsonObject + ("native_execute" to JsonPrimitive(true))
        assertThrows(Exception::class.java) {
            AgentMissionView.decode(JsonObject(p+("permissions" to JsonObject(permissions))),source,capsule,scope)
        }
        assertThrows(Exception::class.java) {
            AgentMissionView.decode(JsonObject(p+("provider_id" to JsonPrimitive("fake-live"))),source,capsule,scope)
        }
    }
    @Test fun sourceMismatchAndCompletedWithoutReceiptAreRejected() {
        assertThrows(Exception::class.java) { AgentMissionView.decode(pending(),"2".repeat(40),capsule,scope) }
        assertThrows(Exception::class.java) {
            AgentMissionView.decode(JsonObject(pending()+("state" to JsonPrimitive("AGENT_COMPLETED"))),source,capsule,scope)
        }
    }
    @Test fun unknownNeverBecomesStoppableOrCompletedByLocalState() {
        val fresh = Freshness(1,"FRESH",2000)
        assertFalse(fresh.canStop("AGENT_UNKNOWN",1000))
        assertTrue(fresh.canStop("AGENT_RUNNING",1000))
        assertFalse(fresh.canStop("AGENT_COMPLETED",1000))
    }
}
