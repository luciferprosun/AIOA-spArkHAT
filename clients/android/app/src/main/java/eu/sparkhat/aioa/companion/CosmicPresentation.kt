package eu.sparkhat.aioa.companion

import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlinx.serialization.json.*

internal fun pageLabel(page: String): Int = when(page) {
    "home" -> R.string.nav_home
    "chat" -> R.string.nav_chat
    "missions" -> R.string.nav_missions
    "critical" -> R.string.nav_critical
    "repositories" -> R.string.nav_repositories
    "devices" -> R.string.nav_devices
    "approvals" -> R.string.nav_approvals
    "details" -> R.string.nav_details
    "activity" -> R.string.nav_activity
    "providers" -> R.string.nav_providers
    "recovery" -> R.string.nav_recovery
    "settings" -> R.string.nav_settings
    else -> R.string.advanced_enrollment
}

internal fun stateResource(state: String): Int = when(state) {
    "REMOTE_DEPLOYMENT_BLOCKED" -> R.string.state_deployment_blocked
    "DISCONNECTED" -> R.string.state_disconnected
    "STALE" -> R.string.state_stale
    "UNKNOWN","OFFLINE_OR_DENIED" -> R.string.state_unknown
    "UNVERIFIED" -> R.string.state_unverified
    "SIGNED_SESSION","CONNECTED" -> R.string.state_connected
    "RECONNECTING" -> R.string.recovery_connecting
    "WAITING_NETWORK" -> R.string.recovery_waiting_network
    "SESSION_EXPIRED" -> R.string.recovery_session_expired
    "MANUAL_RECOVERY" -> R.string.recovery_manual_required
    "AUTO_RECOVERY_PAUSED" -> R.string.recovery_paused
    "FRESH_ENROLLMENT_REQUIRED","RECOVERY_REQUIRED" -> R.string.state_recovery
    "CONFIRM_HOST" -> R.string.state_confirm
    "PENDING" -> R.string.state_pending
    "APPROVED" -> R.string.state_approved
    "COMPLETED" -> R.string.state_completed
    "PAIRING_SAVED" -> R.string.state_pairing_saved
    "REVOKED" -> R.string.state_revoked
    "EXPIRED" -> R.string.state_expired
    "BEGIN_UNCERTAIN" -> R.string.state_begin_uncertain
    else -> R.string.state_unknown
}


/** Home distinguishes public pairing history from live, signed session evidence. */
private fun MissionUi.currentConnectionState(now: Long): String = when {
    connection in setOf("SIGNED_SESSION","CONNECTED") && (!enrolled || bindingInvalid) -> "RECOVERY_REQUIRED"
    connection in setOf("SIGNED_SESSION","CONNECTED") && !freshness.isFresh(now) -> "STALE"
    else -> connection
}
internal fun MissionUi.connectionLabel(now: Long = Freshness.elapsedMs()): Int = stateResource(currentConnectionState(now))
internal fun MissionUi.pairingLabel(): Int = stateResource(if (pairingState == "CONNECTED") "PAIRING_SAVED" else pairingState)
internal fun MissionUi.reconnectLabel(now: Long = Freshness.elapsedMs()): Int =
    if (currentConnectionState(now) in setOf("SIGNED_SESSION","CONNECTED")) R.string.refresh_connection else R.string.recover_session


internal enum class PrimaryAction { CONNECT, CONFIRM, PAIRING_STATUS, RECONNECT, STATUS }

/** The same state decision drives each primary control and its adjacent explanation. */
internal fun MissionUi.primaryDisabledReason(action: PrimaryAction, nowSeconds: Long): Int? {
    if (busy) return R.string.reason_busy
    if (bindingInvalid) return R.string.reason_invalid_binding
    return when(action) {
        PrimaryAction.CONNECT -> null
        PrimaryAction.CONFIRM -> when {
            invite == null -> R.string.reason_no_invite
            nowSeconds >= invite.expiresAt -> R.string.reason_expired
            else -> null
        }
        PrimaryAction.PAIRING_STATUS -> when {
            pairing == null -> R.string.reason_no_pairing
            pairingState == "REVOKED" -> R.string.reason_revoked
            enrolled -> R.string.reason_already_connected
            pairingState == "EXPIRED" || nowSeconds >= pairing.expiresAt -> R.string.reason_expired
            else -> null
        }
        PrimaryAction.RECONNECT -> when {
            pairing == null -> R.string.reason_no_pairing
            pairingState == "REVOKED" -> R.string.reason_revoked
            pairing.trusted || pairing.completeAttempted -> null
            pairingState == "EXPIRED" || nowSeconds >= pairing.expiresAt -> R.string.reason_expired
            else -> R.string.reason_pairing_pending
        }
        PrimaryAction.STATUS -> when {
            pairingState == "REVOKED" -> R.string.reason_revoked
            !enrolled -> R.string.reason_no_session
            else -> null
        }
    }
}

internal fun formatSignedHostTime(epochSeconds: Long): String =
    DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm:ss 'UTC'",Locale.ROOT)
        .withZone(ZoneOffset.UTC).format(Instant.ofEpochSecond(epochSeconds))

/** UI availability only; the ViewModel and existing Core recheck the operation. */
internal fun MissionUi.taskStopReason(agent: Boolean, now: Long = Freshness.elapsedMs()): Int? {
    if (busy) return R.string.reason_busy
    if (bindingInvalid) return R.string.reason_invalid_binding
    if (!enrolled) return R.string.reason_no_session
    if (capabilities?.get("stop")?.jsonPrimitive?.booleanOrNull!=true ||
        (agent && capabilities?.get("profile")?.jsonPrimitive?.content!="OFFLINE_FIXTURE")) return R.string.cosmic_not_available
    val selected=if(agent) agentTask else task
    if(selected==null) return R.string.cosmic_no_missions
    if(requestedTask!=null && !requestedTask.matches(selected,agent)) return R.string.master_selected_task_pending
    if(!freshness.isFresh(now) || !readbacks.isFresh(selected,agent,now)) return R.string.master_task_readback_required
    if(!readbacks.canStop(selected,agent,now)) return R.string.master_task_terminal
    return null
}
internal fun MissionUi.gitPreviewReason(now: Long = Freshness.elapsedMs()): Int? {
    if (busy) return R.string.reason_busy
    if (bindingInvalid) return R.string.reason_invalid_binding
    if (!enrolled) return R.string.reason_no_session
    if (capabilities?.get("profile")?.jsonPrimitive?.content!="OFFLINE_FIXTURE") return R.string.cosmic_not_available
    if(pendingAgent!=null) return R.string.master_pending_agent
    val selected=detailTask(true) ?: return R.string.master_selected_task_pending
    if(!freshness.isFresh(now) || !readbacks.isFresh(selected,true,now)) return R.string.master_task_readback_required
    val operation=selected["operation"] as? JsonObject
    if(selected["state"]?.jsonPrimitive?.content!="AGENT_COMPLETED" || selected["receipt"]==null || selected["receipt"]==JsonNull ||
        operation?.get("operation_class")?.jsonPrimitive?.content!="SANDBOX_EXEC") return R.string.master_git_source_required
    return null
}
internal fun phaseResource(phase: CosmicPhase): Int = when(phase) {
    CosmicPhase.SIGNED -> R.string.master_state_signed
    CosmicPhase.DISCONNECTED -> R.string.state_disconnected
    CosmicPhase.CONNECTING -> R.string.recovery_connecting
    CosmicPhase.EXPIRED -> R.string.state_expired
    CosmicPhase.PENDING -> R.string.master_state_pending
    CosmicPhase.RUNNING -> R.string.master_state_running
    CosmicPhase.SUCCEEDED -> R.string.master_state_succeeded
    CosmicPhase.FAILED -> R.string.master_state_failed
    CosmicPhase.REVOKED -> R.string.state_revoked
    CosmicPhase.STOPPED -> R.string.master_state_stopped
    CosmicPhase.DISABLED -> R.string.cosmic_not_available
    CosmicPhase.UNKNOWN -> R.string.state_unknown
}
