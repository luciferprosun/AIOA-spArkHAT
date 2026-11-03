package eu.sparkhat.aioa.companion

import kotlinx.serialization.json.*

data class UiMessage(val resource: Int, val arguments: List<String> = emptyList())
data class RequestedTask(val id: String, val agent: Boolean) {
    init { require((if(agent) AgentMissionView.taskPattern else Wire.taskId).matches(id)) }
    fun matches(data: JsonObject, agent: Boolean) = this.agent==agent && id==Wire.text(data,"task_id")
}

data class MissionUi(
    val freshness: Freshness = Freshness(), val busy: Boolean = false, val enrolled: Boolean = false,
    val connection: String = "REMOTE_DEPLOYMENT_BLOCKED", val task: JsonObject? = null,
    val pending: String? = null, val archived: List<String> = emptyList(),
    val missions: List<JsonObject> = emptyList(), val nextCursor: String? = null,
    val agentTask: JsonObject? = null, val agentMissions: List<JsonObject> = emptyList(),
    val pendingAgent: String? = null, val archivedAgents: List<String> = emptyList(),
    val providers: JsonObject? = null,
    val readbacks: TaskReadbacks = TaskReadbacks(), val history: List<UiHistoryEvent> = emptyList(),
    val requestedTask: RequestedTask? = null,
    val invite: PairingInvite? = null, val pairing: PairingRecord? = null,
    val pairingState: String = "DISCONNECTED", val capabilities: JsonObject? = null, val bindingInvalid: Boolean = false,
    val lastSignedResponseAt: Long? = null, // historical verified v1 proof time, memory only
    val message: UiMessage = UiMessage(R.string.initial)
)
fun MissionUi.sessionUnavailable() = copy(enrolled=false,readbacks=readbacks.invalidate())
internal fun MissionUi.requestTask(id: String, agent: Boolean) =
    copy(requestedTask=RequestedTask(id,agent),readbacks=readbacks.invalidate())
internal fun MissionUi.detailTask(agent: Boolean): JsonObject? =
    (if(agent) agentTask else task)?.takeIf { requestedTask==null || requestedTask.matches(it,agent) }

/** Called only after MobileClient's signed source/scope/schema validation. */
internal fun MissionUi.observeTask(data: JsonObject, agent: Boolean, expectedId: String? = null): MissionUi {
    val id=Wire.text(data,"task_id")
    require((if(agent) AgentMissionView.taskPattern else Wire.taskId).matches(id))
    require(expectedId==null || expectedId==id)
    val previous=if(agent) agentTask else task
    if(previous!=null && Wire.text(previous,"task_id")==id) {
        require(Wire.text(previous,"task_digest")==Wire.text(data,"task_digest"))
    }
    val issued=lastSignedResponseAt ?: error("SIGNED_TASK_OBSERVATION_REQUIRED")
    val observations=readbacks.accept(data,agent,freshness.validUntilElapsedMs,issued)
    val selected=if(expectedId!=null || requestedTask==null) RequestedTask(id,agent) else requestedTask
    return if(agent) copy(agentTask=data,readbacks=observations,requestedTask=selected)
        else copy(task=data,readbacks=observations,requestedTask=selected)
}
