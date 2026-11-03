package eu.sparkhat.aioa.companion

import kotlinx.serialization.json.*

/** Presentation metadata only. Core and signed transport remain the authority. */
data class TaskObservation(val payloadSha: String, val untilElapsedMs: Long, val atEpochSeconds: Long) {
    fun matches(task: JsonObject) = payloadSha == Wire.sha(Wire.canonical(task))
    fun isFresh(task: JsonObject, now: Long) = matches(task) && now < untilElapsedMs
    fun invalidate() = copy(untilElapsedMs=0)
}

data class TaskReadbacks(val document: TaskObservation? = null, val agent: TaskObservation? = null) {
    fun invalidate() = copy(document=document?.invalidate(),agent=agent?.invalidate())
    fun accept(task: JsonObject, agent: Boolean, until: Long, issuedAt: Long): TaskReadbacks {
        require(until>0 && issuedAt>=0)
        val observation=TaskObservation(Wire.sha(Wire.canonical(task)),until,issuedAt)
        return if(agent) copy(agent=observation) else copy(document=observation)
    }
    fun isFresh(task: JsonObject, agent: Boolean, now: Long = Freshness.elapsedMs()): Boolean =
        (if(agent) this.agent else document)?.isFresh(task,now)==true
    fun observedAt(task: JsonObject, agent: Boolean): Long? =
        (if(agent) this.agent else document)?.takeIf { it.matches(task) }?.atEpochSeconds
    fun canStop(task: JsonObject, agent: Boolean, now: Long = Freshness.elapsedMs()): Boolean {
        val state=(task["state"] as? JsonPrimitive)?.content ?: return false
        val observation=(if(agent) this.agent else document) ?: return false
        return observation.matches(task) && Freshness(0,"FRESH",observation.untilElapsedMs).canStop(state,now)
    }
}

enum class CosmicPhase { SIGNED, DISCONNECTED, CONNECTING, EXPIRED, PENDING, RUNNING, SUCCEEDED, FAILED, REVOKED, STOPPED, DISABLED, UNKNOWN }

/** Completion is an observed state plus an actual receipt; it never proves LIVE. */
internal fun missionPhase(task: JsonObject): CosmicPhase {
    val state=(task["state"] as? JsonPrimitive)?.content ?: return CosmicPhase.UNKNOWN
    return when(state) {
        "PREVIEWED","AGENT_PENDING","AGENT_APPROVED","LIVE_PENDING_AUTHORIZATION" -> CosmicPhase.PENDING
        "RUNNING","AGENT_RUNNING" -> CosmicPhase.RUNNING
        "AGENT_COMPLETED","OFFLINE_FIXTURE" ->
            if(task["receipt"]!=null && task["receipt"]!=JsonNull) CosmicPhase.SUCCEEDED else CosmicPhase.UNKNOWN
        "AGENT_FAILED","FAILED","DENIED" -> CosmicPhase.FAILED
        "AGENT_STOPPED","STOPPED" -> CosmicPhase.STOPPED
        "REVOKED" -> CosmicPhase.REVOKED
        "BLOCKED" -> CosmicPhase.DISABLED
        else -> CosmicPhase.UNKNOWN
    }
}

enum class UiEventKind { SIGNED_READBACK, LOCAL_UNKNOWN, LOCAL_SESSION_LOST }
data class UiHistoryEvent(val kind: UiEventKind, val atEpochSeconds: Long, val taskId: String? = null) {
    val signed get() = kind==UiEventKind.SIGNED_READBACK
}
/** Bounded memory-only metadata; no message bodies, bearer, key, invitation or code. */
internal fun appendUiHistory(history: List<UiHistoryEvent>, event: UiHistoryEvent): List<UiHistoryEvent> {
    require(event.atEpochSeconds>=0)
    require(event.taskId==null || Wire.taskId.matches(event.taskId) || AgentMissionView.taskPattern.matches(event.taskId))
    return (history+event).takeLast(32)
}
