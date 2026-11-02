package eu.sparkhat.aioa.companion

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import java.util.UUID
import kotlinx.coroutines.Job
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*

data class MissionUi(
    val freshness: Freshness = Freshness(), val busy: Boolean = false, val enrolled: Boolean = false,
    val connection: String = "REMOTE_DEPLOYMENT_BLOCKED", val task: JsonObject? = null,
    val pending: String? = null, val archived: List<String> = emptyList(),
    val missions: List<JsonObject> = emptyList(), val nextCursor: String? = null,
    val agentTask: JsonObject? = null, val agentMissions: List<JsonObject> = emptyList(),
    val pendingAgent: String? = null, val archivedAgents: List<String> = emptyList(),
    val providers: JsonObject? = null,
    val invite: PairingInvite? = null, val pairing: PairingRecord? = null,
    val pairingState: String = "DISCONNECTED", val capabilities: JsonObject? = null, val bindingInvalid: Boolean = false,
    val message: String = "Verified HTTPS and fresh enrollment required; owner NOT_BOUND."
)
fun MissionUi.sessionUnavailable() = copy(enrolled=false)

class MissionViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("mobile-ui-v1",0)
    private val client = MobileClient(TransportIdentity())
    private var generation = Freshness()
    private val trustedHosts = TrustedHostStore(app)
    private val transportMutex = Mutex()
    private var pairingJob: Job? = null
    private var pairingPolls = 0
    private fun now() = System.currentTimeMillis()/1000
    val publicSpki get() = client.publicSpki
    var ui by mutableStateOf(MissionUi(pending=prefs.getString("pending_proposal",null),
        pendingAgent=prefs.getString("pending_agent_proposal",null),
        archivedAgents=prefs.getStringSet("unresolved_agent_proposals",emptySet())!!.filter { Wire.hex32.matches(it) }.sorted(),
        archived=prefs.getStringSet("unresolved_proposals",emptySet())!!.filter { Wire.hex32.matches(it) }.sorted()))
        private set

    init {
        try { ui = ui.copy(pairing=trustedHosts.load(),message="Connect to your AIOA or reconnect a saved host.") }
        catch (_: Exception) { ui = ui.copy(bindingInvalid=true,message="Saved host metadata is invalid. Forget it in Settings and scan your trusted Linux display.") }
    }
    fun scannerMessage(message: String) { ui = ui.copy(message=message) }
    fun importPacket(raw: String) {
        if (ui.busy) return
        try {
            check(!ui.bindingInvalid) { "HOST_BINDING_INVALID" }
            val invite = PairingProtocol.parseInvite(raw,now())
            ui.pairing?.host?.requireSameBinding(invite.host)
            ui = ui.copy(invite=invite,pairingState="CONFIRM_HOST",message="Confirm this host only if the QR came from your trusted Linux display.")
        } catch (_: Exception) { ui = ui.copy(invite=null,message="Invalid, expired or changed host packet. Check the phone clock; obtain a new QR. A different host requires explicit Forget in Settings.") }
    }
    private fun pairingFlow(work: suspend () -> Unit) {
        if (ui.busy || pairingJob?.isActive == true) return
        generation = generation.invalidate("STALE")
        ui = ui.copy(busy=true,enrolled=false,freshness=generation)
        pairingJob = viewModelScope.launch {
            try { transportMutex.withLock { work() } }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) {
                client.close()
                ui = ui.copy(enrolled=false,connection="UNKNOWN",pairingState="RECOVERY_REQUIRED",
                    message=when {
                        failure is PairingFailure -> "Rate limited. Polling stopped; wait before an explicit readback."
                        failure is SessionUnavailable -> "Session unavailable. Reconnect explicitly; revoked devices need a new QR and Linux approval."
                        failure.message == "INVITE_EXPIRED" -> "Invitation expired. Polling stopped; obtain a fresh QR or recover an already completed session."
                        failure.message == "HOST_BINDING_CHANGED" -> "Host identity or owner scope changed. Connection blocked."
                        else -> "Connection uncertain or denied. No automatic mutation retry. Read pairing status or explicitly recover a completed connection."
                    })
            } finally { ui = ui.copy(busy=false) }
        }
    }
    fun confirmHost() {
        val invite = ui.invite ?: return
        pairingFlow {
            require(now() < invite.expiresAt)
            val host = withContext(Dispatchers.IO) { client.preparePairing(invite.host) }
            require(host.source == invite.host.source && host.capsule == invite.host.capsule)
            val id = UUID.randomUUID().toString().replace("-","")
            val body = client.pairingRequest("/pairing/begin",buildJsonObject {
                put("invite",invite.envelope); put("request_id",id); put("device_name","AIOA Android")
            })
            val record = PairingRecord(host,id,client.beginDigest(body),invite.expiresAt,false,false)
            // Atomic public host + exact request digest precedes the only begin attempt.
            trustedHosts.save(record)
            ui = ui.copy(pairing=record,invite=null,pairingState="BEGIN_UNCERTAIN",capabilities=client.capabilities)
            pairingPolls = 0
            val data = withContext(Dispatchers.IO) { client.pairingExchange("/pairing/begin",body) }
            PairingProtocol.validateStatus(data,record,client.deviceId)
            watchPairing(record,data)
        }
    }
    fun readPairingStatus() {
        val record = ui.pairing ?: return
        pairingFlow {
            require(now() < record.expiresAt) { "INVITE_EXPIRED" }
            val host = withContext(Dispatchers.IO) { client.preparePairing(record.host) }
            // A pending request is tied to the original source/capsule. No rewrite on readback.
            require(host.source == record.host.source && host.capsule == record.host.capsule)
            delay(3100)
            require(now() < record.expiresAt) { "INVITE_EXPIRED" }
            val data = withContext(Dispatchers.IO) { client.pairingStatus(record) }
            watchPairing(record,data)
        }
    }
    private suspend fun watchPairing(initial: PairingRecord, first: JsonObject) {
        var record = initial
        var data = first
        while (true) {
            val state = PairingProtocol.validateStatus(data,record,client.deviceId)
            ui = ui.copy(pairingState=state,message=when(state) {
                "PENDING" -> "Compare the six digits with Linux, then approve the exact device there."
                "REVOKED" -> "Linux revoked or superseded this request. Scan a new QR and obtain exact approval."
                "EXPIRED" -> "Invitation expired. Obtain a new QR."
                "COMPLETED" -> "Pairing completed. Recover a fresh session explicitly; the old token is unavailable."
                else -> "Linux approved this exact device. Finishing the connection…"
            })
            if (state == "COMPLETED" && !record.completeAttempted) {
                record = record.copy(completeAttempted=true)
                trustedHosts.save(record); ui = ui.copy(pairing=record)
            }
            if (state == "REVOKED") {
                record = record.copy(trusted=false,completeAttempted=false)
                trustedHosts.save(record); ui = ui.copy(pairing=record)
            }
            if (state == "APPROVED" && record.completeAttempted) {
                ui = ui.copy(message="The prior completion attempt is uncertain. Recover explicitly with a fresh challenge; completion will not be repeated.")
            }
            if (PairingProtocol.canComplete(state,record.completeAttempted)) {
                record = record.copy(completeAttempted=true)
                trustedHosts.save(record); ui = ui.copy(pairing=record)
                withContext(Dispatchers.IO) { client.completePairing(record) }
                record = record.copy(trusted=true)
                trustedHosts.save(record); ui = ui.copy(pairing=record)
                acceptConnectedStatus()
                return
            }
            if (state != "PENDING") return
            if (now() >= record.expiresAt || pairingPolls >= 98) {
                ui = ui.copy(pairingState="EXPIRED",message="Polling stopped at its time or request limit. Obtain a new QR if needed.")
                return
            }
            delay(3100) // <= 98 polls per 300 second invite, below the server nonce cap128.
            if (now() >= record.expiresAt) {
                ui = ui.copy(pairingState="EXPIRED",message="Invitation expired. Polling stopped; obtain a fresh QR.")
                return
            }
            pairingPolls++
            data = withContext(Dispatchers.IO) { client.pairingStatus(record) }
        }
    }
    fun reconnect() {
        val record = ui.pairing ?: return
        if (!record.trusted && !record.completeAttempted) return
        pairingFlow {
            val host = withContext(Dispatchers.IO) { client.preparePairing(record.host) }
            withContext(Dispatchers.IO) { client.reconnectSession() }
            val updated = record.copy(host=host,trusted=true)
            trustedHosts.save(updated); ui = ui.copy(pairing=updated)
            acceptConnectedStatus()
        }
    }
    private suspend fun acceptConnectedStatus() {
        val observation = withContext(Dispatchers.IO) { client.status() }
        val epoch = generation.generation
        generation = generation.accept(epoch,observation.validUntilElapsedMs)
        ui = ui.copy(enrolled=true,connection="SIGNED_SESSION",pairingState="CONNECTED",capabilities=client.capabilities,
            freshness=generation,message="Connected to your AIOA. Signed status; owner approval remains on Linux.")
        acceptStatus(observation.data)
        viewModelScope.launch {
            delay((observation.validUntilElapsedMs-Freshness.elapsedMs()).coerceAtLeast(0)+1)
            if (generation.generation == epoch) {
                generation = generation.invalidate("STALE")
                ui = ui.copy(freshness=generation,connection="STALE")
            }
        }
    }
    fun forgetHost() {
        if (ui.busy || pairingJob?.isActive == true) return
        try {
            trustedHosts.forget(); client.close(); generation = generation.invalidate("STALE")
            ui = ui.copy(pairing=null,invite=null,enrolled=false,capabilities=null,bindingInvalid=false,pairingState="DISCONNECTED",
                freshness=generation,connection="DISCONNECTED",message="Local host binding forgotten. Linux device approval is unchanged; revoke it on Linux. Pending mission IDs remain retained.")
        } catch (_: Exception) { ui = ui.copy(message="Could not forget local binding; it remains retained.") }
    }
    fun supports(name: String) = ui.enrolled && ui.capabilities?.get(name)?.jsonPrimitive?.booleanOrNull == true
    val agentAvailable get() = ui.enrolled && ui.capabilities?.get("profile")?.jsonPrimitive?.content == "OFFLINE_FIXTURE"

    private fun request(op: () -> MobileObservation, apply: (JsonObject) -> Unit) {
        if (ui.busy || pairingJob?.isActive == true) return
        generation = generation.invalidate("STALE")
        val epoch = generation.generation
        ui = ui.copy(freshness=generation,busy=true,message="Waiting for signed readback…")
        viewModelScope.launch {
            try {
                val observation = withContext(Dispatchers.IO) { transportMutex.withLock { op() } }
                if (generation.generation == epoch) {
                    val validUntilElapsedMs = observation.validUntilElapsedMs
                    generation = generation.accept(epoch,validUntilElapsedMs)
                    ui = ui.copy(freshness=generation,busy=false,connection="SIGNED_SESSION")
                    apply(observation.data)
                    viewModelScope.launch {
                        delay((validUntilElapsedMs-Freshness.elapsedMs()).coerceAtLeast(0)+1)
                        if (generation.generation == epoch) {
                            generation = generation.invalidate("STALE")
                            ui = ui.copy(freshness=generation,connection="STALE",message="Proof expired; request signed GET/readback.")
                        }
                    }
                }
            } catch (_: SessionUnavailable) {
                if (generation.generation == epoch) {
                    generation = generation.invalidate("UNKNOWN")
                    ui = ui.sessionUnavailable().copy(freshness=generation,busy=false,connection="FRESH_ENROLLMENT_REQUIRED",
                        message="Session unavailable. Reconnect the saved host, or scan a new QR if revoked. Pending/UNKNOWN still needs host readback or reconciliation.")
                }
            } catch (_: Exception) {
                if (generation.generation == epoch) {
                    generation = generation.invalidate("UNKNOWN")
                    ui = ui.copy(freshness=generation,busy=false,connection="OFFLINE_OR_DENIED",
                        message="UNKNOWN: read state; do not repeat POST. Check HTTPS, host permissions and session time.")
                }
            }
        }
    }
    fun connect(origin: String, tlsPin: String, hostKey: String, code: String) {
        if (ui.busy) return
        ui = ui.copy(enrolled=false,task=null,missions=emptyList(),nextCursor=null,agentTask=null,
            agentMissions=emptyList(),providers=null,connection="UNVERIFIED")
        request({
            check(!ui.bindingInvalid) { "HOST_BINDING_INVALID" }
            val binding = ui.pairing?.host
            if (binding != null) {
                require(origin == binding.origin && tlsPin == binding.tlsPin && hostKey == binding.spki) { "HOST_BINDING_CHANGED" }
                client.preparePairing(binding)
            } else client.configure(origin,tlsPin,hostKey)
            client.enroll(code)
        }) {
            ui = ui.copy(enrolled=true,capabilities=client.capabilities,message="Fresh transport session; owner NOT_BOUND. Read status.")
        }
    }
    fun status() = request({ client.status() },::acceptStatus)
    fun older() {
        val cursor = ui.nextCursor ?: return
        request({ client.statusPage(cursor) },::acceptStatus)
    }
    fun selectTask(taskId: String) = request({ client.evidence(taskId) }) { acceptTask(it) }
    private fun acceptStatus(data: JsonObject) {
        val missions = data.getValue("missions").jsonArray
        val current = ui.task?.let { Wire.text(it,"task_id") }
        val selected = missions.map { it.jsonObject }.firstOrNull { current == null || Wire.text(it,"task_id") == current }
        ui = ui.copy(missions=missions.map { it.jsonObject },nextCursor=if(data["next_cursor"]==JsonNull) null else Wire.text(data,"next_cursor"))
        val visible = selected ?: missions.firstOrNull()?.jsonObject
        if (visible != null) acceptTask(visible) else ui = ui.copy(task=null,message="No tasks of yours on this page.")
    }
    fun preview(instruction: String) {
        if (!supports("preview") || ui.pending != null || !ui.freshness.isFresh() || !ui.enrolled || ui.busy) return
        val proposal = UUID.randomUUID().toString().replace("-","")
        // Opaque proposal ID only. Persist before the single POST; no token/code/content.
        if (!prefs.edit().putString("pending_proposal",proposal).commit()) return
        ui = ui.copy(pending=proposal)
        request({ client.preview(proposal,instruction) }) { data -> acceptTask(data); clearPending() }
    }
    fun readback() {
        val proposal = ui.pending ?: return
        request({ client.readback(proposal) }) { data ->
            if (Wire.text(data,"state") == "UNKNOWN") {
                ui = ui.copy(message="UNKNOWN: host operator reconciliation required; no automatic retry.")
            } else { acceptTask(data); clearPending() }
        }
    }
    private fun clearPending() {
        prefs.edit().remove("pending_proposal").apply(); ui = ui.copy(pending=null)
    }
    fun archivePendingHint() {
        if (ui.busy) return
        val proposal = ui.pending ?: return
        try {
            val history = PendingHints.archive(proposal,ui.archived)
            if (prefs.edit().putStringSet("unresolved_proposals",history.toSet()).remove("pending_proposal").commit()) {
                ui = ui.copy(pending=null,archived=history,
                    message="ID retained for host reconciliation. Core UNKNOWN is unchanged; no retry or effect.")
            }
        } catch (_: Exception) { ui = ui.copy(message="Cannot retain local ID; pending remains blocked.") }
    }
    private fun acceptTask(data: JsonObject) {
        val previous = ui.task
        if (previous != null && Wire.text(previous,"task_id") == Wire.text(data,"task_id")) {
            require(Wire.text(previous,"task_digest") == Wire.text(data,"task_digest"))
        }
        ui = ui.copy(task=data,message="Signed state: ${Wire.text(data,"state")}; model/browser LIVE unverified.")
    }
    fun evidence() {
        val task = ui.task ?: return
        request({ client.evidence(Wire.text(task,"task_id")) }) { acceptTask(it) }
    }
    fun stop() {
        val task = ui.task ?: return
        if (!ui.freshness.canStop(Wire.text(task,"state")) || ui.busy) return
        request({ client.stop(Wire.text(task,"task_id")) }) { acceptTask(it) }
    }
    fun revoke() = request({ client.revoke() }) {
        generation = generation.invalidate(); ui = MissionUi(freshness=generation,pending=ui.pending,archived=ui.archived,
            pendingAgent=ui.pendingAgent,archivedAgents=ui.archivedAgents,pairing=ui.pairing,
            message="Session revoked. Saved device approval remains on Linux; reconnect is still possible. Revoke the device on Linux to prevent reconnect.")
    }
    fun agentStatus() = request({ client.agentStatus() }) { data ->
        ui = ui.copy(agentMissions=data.getValue("missions").jsonArray.map { it.jsonObject },
            message="Signed agent status. Exact approval stays on the Linux host.")
    }
    fun agentProviders() = request({ client.agentProviders() }) { data -> ui = ui.copy(providers=data) }
    fun agentSelect(taskId: String) = request({ client.agentEvidence(taskId) }) { data ->
        val previous = ui.agentTask
        if (previous != null && Wire.text(previous,"task_id") == Wire.text(data,"task_id")) {
            require(Wire.text(previous,"task_digest") == Wire.text(data,"task_digest"))
        }
        ui = ui.copy(agentTask=data,message="Signed agent view; model LIVE remains unverified.")
    }
    private fun proposeAgent(sourceTask: String? = null) {
        if (!agentAvailable || ui.pendingAgent != null || !ui.freshness.isFresh() || !ui.enrolled || ui.busy) return
        val proposal = UUID.randomUUID().toString().replace("-","")
        if (!prefs.edit().putString("pending_agent_proposal",proposal).commit()) return
        ui = ui.copy(pendingAgent=proposal)
        request({ client.agentProposal(proposal,sourceTask) }) { data ->
            prefs.edit().remove("pending_agent_proposal").apply()
            ui = ui.copy(agentTask=data,pendingAgent=null,message="NEEDS_HOST_APPROVAL: review the exact operation on Linux.")
        }
    }
    fun proposeSensorBridge() = proposeAgent()
    fun proposeGit() {
        val task = ui.agentTask ?: return
        if (Wire.text(task,"state") != "AGENT_COMPLETED") return
        val operation = task.getValue("operation").jsonObject
        if (Wire.text(operation,"operation_class") != "SANDBOX_EXEC") return
        proposeAgent(Wire.text(task,"task_id"))
    }
    fun agentReadback() {
        val proposal = ui.pendingAgent ?: return
        request({ client.agentReadback(proposal) }) { data ->
            if (data["task_id"] == null) ui = ui.copy(message="UNKNOWN: host readback required; no POST retry.")
            else {
                prefs.edit().remove("pending_agent_proposal").apply()
                ui = ui.copy(agentTask=data,pendingAgent=null,message="Signed proposal readback.")
            }
        }
    }
    fun archivePendingAgentHint() {
        if (ui.busy) return
        val proposal = ui.pendingAgent ?: return
        try {
            val history = PendingHints.archive(proposal,ui.archivedAgents)
            if (prefs.edit().putStringSet("unresolved_agent_proposals",history.toSet())
                    .remove("pending_agent_proposal").commit()) {
                ui = ui.copy(pendingAgent=null,archivedAgents=history,
                    message="Agent ID retained for the host. Core UNKNOWN is unchanged; no retry or effect.")
            } else ui = ui.copy(message="Cannot retain agent ID; pending remains blocked.")
        } catch (_: Exception) { ui = ui.copy(message="Cannot retain agent ID; pending remains blocked.") }
    }
    fun agentEvidence() {
        val task = ui.agentTask ?: return
        agentSelect(Wire.text(task,"task_id"))
    }
    fun agentStop() {
        val task = ui.agentTask ?: return
        if (!ui.freshness.canStop(Wire.text(task,"state")) || ui.busy) return
        request({ client.agentStop(Wire.text(task,"task_id")) }) { data ->
            ui = ui.copy(agentTask=data,message="STOP observed. UNKNOWN never grants a retry.")
        }
    }
    fun background() {
        pairingJob?.cancel()
        generation = generation.invalidate("STALE"); client.cancel()
        ui = ui.copy(freshness=generation,busy=false,connection="STALE",message="Resume requires signed GET/readback.")
    }
    fun resume() {
        generation = generation.invalidate("STALE")
        ui = ui.copy(freshness=generation,message=if (ui.pending == null) "Read fresh status." else
            "Unresolved proposal: read back in this session, or contact the host operator after restart.")
    }
    override fun onCleared() { client.close(); super.onCleared() }
}
