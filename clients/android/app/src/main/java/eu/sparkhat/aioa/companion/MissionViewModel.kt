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

class MissionViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("mobile-ui-v1",0)
    private val client = MobileClient(TransportIdentity())
    private var generation = Freshness()
    private val trustedHosts = TrustedHostStore(app)
    private var bindingOwner: BindingOwner? = null
    private val transportMutex = Mutex()
    private var pairingJob: Job? = null
    private var requestJob: Job? = null
    private var pairingPolls = 0
    private var foreground = false
    private val recoveryWork = RecoveryWorkQueue()
    private var recoveryBlocked = false
    private val recoveryWake = RecoveryWakeGate()
    private val recoveryHints = object : RecoveryCheckpoint {
        override fun pending(binding: String) = prefs.getString("pending_reconnect_binding",null) == binding
        override fun mark(binding: String) {
            check(prefs.edit().putString("pending_reconnect_binding",binding).commit()) { "LOCAL_BINDING_SAVE_FAILED" }
        }
        override fun clear(binding: String) {
            if (pending(binding)) check(prefs.edit().remove("pending_reconnect_binding").commit()) { "LOCAL_BINDING_SAVE_FAILED" }
        }
        override fun paused(binding: String) = prefs.getString("paused_recovery_binding",null) == binding
        override fun pause(binding: String) {
            check(prefs.edit().putString("paused_recovery_binding",binding).commit()) { "LOCAL_BINDING_SAVE_FAILED" }
        }
        override fun resume(binding: String) {
            if (paused(binding)) check(prefs.edit().remove("paused_recovery_binding").commit()) { "LOCAL_BINDING_SAVE_FAILED" }
        }
    }
    private val recovery = SessionRecovery(object : SessionRecoveryPort<MobileObservation> {
        override fun hasSession() = client.hasSession()
        override suspend fun prepare(host: TrustedHost) = pairingIo { client.preparePairing(host) }
        override suspend fun reconnect() = pairingIo { client.reconnectSession() }
        override suspend fun status() = pairingIo { client.status() }
    },recoveryHints,guard={
        owner().requireCurrent()
        if (!foreground) throw CancellationException("BACKGROUND_READBACK_STALE")
    })
    private val network = RecoveryNetworkMonitor(app) { available ->
        viewModelScope.launch { networkChanged(available) }
    }
    private fun now() = System.currentTimeMillis()/1000
    val publicSpki get() = client.publicSpki
    var ui by mutableStateOf(MissionUi(pending=prefs.getString("pending_proposal",null),
        pendingAgent=prefs.getString("pending_agent_proposal",null),
        archivedAgents=prefs.getStringSet("unresolved_agent_proposals",emptySet())!!.filter { Wire.hex32.matches(it) }.sorted(),
        archived=prefs.getStringSet("unresolved_proposals",emptySet())!!.filter { Wire.hex32.matches(it) }.sorted()))
        private set

    init {
        try { bindingOwner = BindingOwner(trustedHosts,client::close); ui = ui.copy(pairing=owner().record,bindingInvalid=owner().invalid,message=UiMessage(if(owner().invalid) R.string.binding_invalid else R.string.welcome)) }
        catch (_: Exception) { ui = ui.copy(bindingInvalid=true,message=UiMessage(R.string.binding_invalid)) }
    }
    private fun owner() = bindingOwner ?: error("HOST_BINDING_INVALID")
    private fun reconcileBinding() {
        if (owner().reconcile()) {
            UsbReadback.clear(); generation = generation.invalidate("STALE")
            ui = ui.copy(pairing=owner().record,bindingInvalid=owner().invalid,invite=null,enrolled=false,capabilities=null,lastSignedResponseAt=null,
                freshness=generation,readbacks=ui.readbacks.invalidate(),connection="STALE",pairingState="DISCONNECTED")
        }
    }
    fun deliverPacket(raw: String): Boolean {
        if (ui.busy || recoveryWork.busy) return false
        return try { reconcileBinding(); owner().deliver(raw,::importPacket) }
        catch (_: Exception) { ui = ui.copy(bindingInvalid=true); false }
    }
    fun scannerMessage(resource: Int) { ui = ui.copy(message=UiMessage(resource)) }
    fun importPacket(raw: String): Boolean {
        if (ui.busy || recoveryWork.busy) return false
        return try {
            owner().requireCurrent()
            check(!ui.bindingInvalid) { "HOST_BINDING_INVALID" }
            val invite = PairingProtocol.parseInvite(raw,now())
            owner().record?.host?.requireSameBinding(invite.host)
            ui = ui.copy(invite=invite,lastSignedResponseAt=null,pairingState="CONFIRM_HOST",message=UiMessage(R.string.confirm_notice))
            true
        } catch (_: Exception) { ui = ui.copy(invite=null,message=UiMessage(R.string.packet_invalid)); false }
    }
    private fun pairingFlow(work: suspend () -> Unit) {
        if (ui.busy || recoveryWork.busy) return
        val ticket=Any();recoveryWork.start(ticket)
        UsbReadback.clear(); generation = generation.invalidate("STALE")
        ui = ui.copy(busy=true,enrolled=false,freshness=generation,readbacks=ui.readbacks.invalidate())
        pairingJob = viewModelScope.launch {
            try { transportMutex.withLock { owner().requireCurrent(); work(); owner().requireCurrent() } }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) {
                client.close()
                if (failure is StaleBindingOwner) reconcileBinding()
                val problem = PairingProblem.from(failure)
                if (problem in setOf(PairingProblem.TLS,PairingProblem.PROOF,PairingProblem.BINDING_CHANGED,
                        PairingProblem.SOURCE_CHANGED,PairingProblem.DENIED) || failure is StaleBindingOwner || failure is PairingFailure) recoveryBlocked=true
                val state = when {
                    failure is RecoveryNeedsManual -> "MANUAL_RECOVERY"
                    failure is SessionUnavailable -> "SESSION_EXPIRED"
                    failure is RecoveryNetworkUnavailable || problem in setOf(PairingProblem.DNS,PairingProblem.NETWORK,PairingProblem.TIMEOUT) -> "WAITING_NETWORK"
                    else -> "UNKNOWN"
                }
                ui = ui.copy(enrolled=false,connection=state,pairingState="RECOVERY_REQUIRED",
                    message=when {
                        failure is StaleBindingOwner -> UiMessage(R.string.stale_owner)
                        failure is PairingFailure -> UiMessage(R.string.rate_limited)
                        failure is SessionUnavailable -> UiMessage(R.string.session_unavailable)
                        failure is RecoveryNeedsManual -> UiMessage(R.string.recovery_manual_required)
                        failure is RecoveryNetworkUnavailable -> UiMessage(R.string.recovery_waiting_network)
                        else -> UiMessage(when (PairingProblem.from(failure)) {
                            PairingProblem.DNS -> R.string.pairing_dns_failed
                            PairingProblem.NETWORK -> R.string.pairing_network_failed
                            PairingProblem.TIMEOUT -> R.string.pairing_timeout
                            PairingProblem.TLS -> R.string.pairing_tls_failed
                            PairingProblem.EXPIRED -> R.string.expired_recovery
                            PairingProblem.BINDING_CHANGED -> R.string.binding_changed
                            PairingProblem.SOURCE_CHANGED -> R.string.pairing_source_changed
                            PairingProblem.PROOF -> R.string.pairing_proof_failed
                            PairingProblem.DENIED -> R.string.pairing_host_denied
                            PairingProblem.UNKNOWN -> R.string.connection_uncertain
                        })
                    })
            }
        }
        pairingJob?.let { trackTransport(it,ticket) }
    }
    private fun trackTransport(job: Job, ticket: Any) {
        job.invokeOnCompletion {
            viewModelScope.launch {
                val wake = recoveryWork.finish(ticket)
                if (!recoveryWork.busy) ui = ui.copy(busy=false)
                if (wake) automaticRecovery()
            }
        }
    }
    private suspend fun <T> pairingIo(work: () -> T): T = withContext(Dispatchers.IO) {
        owner().requireCurrent()
        work().also { owner().requireCurrent() }
    }
    fun confirmHost() {
        val invite = ui.invite ?: return
        pairingFlow {
            require(now() < invite.expiresAt) { "INVITE_EXPIRED" }
            ui = ui.copy(message=UiMessage(R.string.pairing_checking_host))
            val host = pairingIo { client.preparePairing(invite.host) }
            require(host.source == invite.host.source && host.capsule == invite.host.capsule) { "HOST_SOURCE_CHANGED" }
            val id = UUID.randomUUID().toString().replace("-","")
            val body = client.pairingRequest("/pairing/begin",buildJsonObject {
                put("invite",invite.envelope); put("request_id",id); put("device_name","AIOA Android")
            })
            val record = PairingRecord(host,id,client.beginDigest(body),invite.expiresAt,false,false)
            // Atomic public host + exact request digest precedes the only begin attempt.
            owner().save(record)
            ui = ui.copy(pairing=record,invite=null,pairingState="BEGIN_UNCERTAIN",capabilities=client.capabilities,
                message=UiMessage(R.string.pairing_sending_request))
            pairingPolls = 0
            val data = pairingIo { client.pairingExchange("/pairing/begin",body) }
            PairingProtocol.validateStatus(data,record,client.deviceId)
            watchPairing(record,data)
        }
    }
    fun readPairingStatus() {
        val record = ui.pairing ?: return
        pairingFlow {
            require(now() < record.expiresAt) { "INVITE_EXPIRED" }
            val host = pairingIo { client.preparePairing(record.host) }
            // A pending request is tied to the original source/capsule. No rewrite on readback.
            require(host.source == record.host.source && host.capsule == record.host.capsule)
            delay(3100)
            require(now() < record.expiresAt) { "INVITE_EXPIRED" }
            val data = pairingIo { client.pairingStatus(record) }
            watchPairing(record,data)
        }
    }
    private suspend fun watchPairing(initial: PairingRecord, first: JsonObject) {
        var record = initial
        var data = first
        while (true) {
            val state = PairingProtocol.validateStatus(data,record,client.deviceId)
            ui = ui.copy(pairingState=state,message=when(state) {
                "PENDING" -> UiMessage(R.string.compare_notice)
                "REVOKED" -> UiMessage(R.string.revoked_notice)
                "EXPIRED" -> UiMessage(R.string.expired_notice)
                "COMPLETED" -> UiMessage(R.string.completed_notice)
                else -> UiMessage(R.string.approved_notice)
            })
            if (state == "COMPLETED" && !record.completeAttempted) {
                record = record.copy(completeAttempted=true)
                owner().save(record); ui = ui.copy(pairing=record)
            }
            if (state == "REVOKED") {
                record = record.copy(trusted=false,completeAttempted=false)
                owner().save(record); ui = ui.copy(pairing=record)
            }
            if (state == "APPROVED" && record.completeAttempted) {
                ui = ui.copy(message=UiMessage(R.string.complete_uncertain))
            }
            if (PairingProtocol.canComplete(state,record.completeAttempted)) {
                record = record.copy(completeAttempted=true)
                owner().save(record); ui = ui.copy(pairing=record)
                pairingIo { client.completePairing(record) }
                record = record.copy(trusted=true)
                owner().save(record); ui = ui.copy(pairing=record)
                acceptConnectedStatus()
                return
            }
            if (state != "PENDING") return
            if (now() >= record.expiresAt || pairingPolls >= 98) {
                ui = ui.copy(pairingState="EXPIRED",message=UiMessage(R.string.poll_limit))
                return
            }
            delay(3100) // <= 98 polls per 300 second invite, below the server nonce cap128.
            if (now() >= record.expiresAt) {
                ui = ui.copy(pairingState="EXPIRED",message=UiMessage(R.string.poll_expired))
                return
            }
            pairingPolls++
            data = pairingIo { client.pairingStatus(record) }
        }
    }
    fun reconnect() {
        recoverSession(manual=true)
    }
    private fun recoverSession(manual: Boolean) {
        val record = ui.pairing ?: return
        if (!record.trusted && !record.completeAttempted) return
        if (manual) recoveryBlocked=false
        pairingFlow {
            ui = ui.copy(connection="RECONNECTING",message=UiMessage(R.string.recovery_connecting))
            val result = recovery.recover(record,manual,network.available)
            owner().requireCurrent()
            val updated = record.copy(host=result.host,trusted=true)
            owner().save(updated); ui = ui.copy(pairing=updated)
            acceptObservation(result.observation)
            recovery.accept(result)
        }
    }
    private fun automaticRecovery() {
        val record = ui.pairing ?: return
        if (!foreground || !record.trusted || ui.bindingInvalid || ui.pairingState == "REVOKED" || recoveryBlocked) return
        if (recoveryHints.paused(SessionRecovery.binding(record))) {
            ui = ui.copy(connection="AUTO_RECOVERY_PAUSED",message=UiMessage(R.string.recovery_paused))
            return
        }
        if (ui.busy || recoveryWork.busy) {
            recoveryWork.defer()
            return
        }
        val uncertain = recoveryHints.pending(SessionRecovery.binding(record)) && !client.hasSession()
        if (uncertain) {
            ui = ui.copy(connection="MANUAL_RECOVERY",message=UiMessage(R.string.recovery_manual_required))
            return
        }
        if (!network.available) {
            ui = ui.copy(connection="WAITING_NETWORK",message=UiMessage(R.string.recovery_waiting_network))
            return
        }
        if (recoveryWake.claim(record.trusted,true,recoveryWork.busy,false)) recoverSession(false)
    }
    private fun networkChanged(available: Boolean) {
        if (!foreground || ui.pairing?.trusted != true) return
        if (!available) {
            pairingJob?.cancel();requestJob?.cancel();client.cancel()
            UsbReadback.clear(); generation = generation.invalidate("STALE")
            ui = ui.copy(freshness=generation,connection="WAITING_NETWORK",message=UiMessage(R.string.recovery_waiting_network))
        } else automaticRecovery()
    }
    private suspend fun acceptConnectedStatus() {
        owner().requireCurrent()
        val observation = pairingIo { client.status() }
        acceptObservation(observation)
    }
    private fun acceptObservation(observation: MobileObservation) {
        owner().requireCurrent()
        val epoch = generation.generation
        generation = generation.accept(epoch,observation.validUntilElapsedMs)
        recoveryWake.accepted()
        recoveryBlocked=false
        ui = ui.copy(enrolled=true,connection="SIGNED_SESSION",pairingState="CONNECTED",capabilities=client.capabilities,
            freshness=generation,readbacks=ui.readbacks.invalidate(),lastSignedResponseAt=observation.issuedAtEpochSeconds,message=UiMessage(R.string.connected_notice))
        acceptStatus(observation.data)
        UsbReadback.accept(observation)
        recordEvent(UiEventKind.SIGNED_READBACK,observation.issuedAtEpochSeconds)
        viewModelScope.launch {
            delay((observation.validUntilElapsedMs-Freshness.elapsedMs()).coerceAtLeast(0)+1)
            if (generation.generation == epoch) {
                UsbReadback.clear(); generation = generation.invalidate("STALE")
                ui = ui.copy(freshness=generation,connection="STALE")
            }
        }
    }
    fun forgetHost() {
        if (ui.busy || recoveryWork.busy) return
        try {
            owner().forget(); client.close(); UsbReadback.clear(); generation = generation.invalidate("STALE")
            ui = ui.copy(pairing=null,invite=null,enrolled=false,capabilities=null,bindingInvalid=false,lastSignedResponseAt=null,pairingState="DISCONNECTED",
                freshness=generation,readbacks=ui.readbacks.invalidate(),connection="DISCONNECTED",message=UiMessage(R.string.forgot_notice))
        } catch (_: Exception) { ui = ui.copy(message=UiMessage(R.string.forget_failed)) }
    }
    fun supports(name: String) = ui.enrolled && ui.capabilities?.get(name)?.jsonPrimitive?.booleanOrNull == true
    val agentAvailable get() = ui.enrolled && ui.capabilities?.get("profile")?.jsonPrimitive?.content == "OFFLINE_FIXTURE"

    val chatAvailable get() = ui.enrolled && client.hasSession() && supports("chat") &&
        ui.capabilities?.get("profile")?.jsonPrimitive?.content=="NATIVE_ADVISORY_CHAT_V1"
    private fun chatBinding()=ui.pairing?.host?.let { Wire.sha((it.origin+"|"+it.tlsPin+"|"+it.spki+"|"+it.ownerScope).toByteArray(Charsets.UTF_8)) }
    fun chatSend(prompt:String) {
        if(!foreground || !ui.chat.canSend(chatAvailable,supports("chat"),ui.busy || recoveryWork.busy,prompt))return
        val id=UUID.randomUUID().toString().replace("-","")
        val thread=ui.chat.threadId ?: UUID.randomUUID().toString().replace("-","")
        val binding=chatBinding() ?: return
        // Public immutable IDs only, committed before the one POST. Never save
        // the prompt, bearer or a replay instruction in preferences.
        if(!prefs.edit().putString("chat_pending",id).putString("chat_thread",thread).putString("chat_binding",binding).commit()) {
            ui=ui.copy(chat=ui.chat.uncertain("LOCAL_BINDING_SAVE_FAILED"));return
        }
        ui=ui.copy(chat=ui.chat.start(id).copy(threadId=thread))
        chatRequest({client.chatSend(thread,id,prompt)},id)
    }
    fun chatRefresh() {
        val id=ui.chat.pendingId ?: ui.chat.messages.lastOrNull()?.requestId ?: return
        chatRequest({client.chatRead(id)},id)
    }
    fun chatStop() {
        val id=ui.chat.pendingId ?: return
        if(ui.chat.state !in setOf("PENDING_OWNER","RUNNING"))return
        chatRequest({client.chatStop(id)},id)
    }
    private fun chatRequest(op:()->MobileObservation,id:String) {
        if(!foreground || ui.busy || recoveryWork.busy || !chatAvailable)return
        val ticket=Any();recoveryWork.start(ticket)
        ui=ui.copy(busy=true,chat=ui.chat.copy(error=null))
        requestJob=viewModelScope.launch {
            try {
                val observation=withContext(Dispatchers.IO) {transportMutex.withLock {owner().requireCurrent();op().also {owner().requireCurrent()}}}
                if(!foreground)throw CancellationException("BACKGROUND_CHAT_READBACK")
                val view=ChatView.decode(observation.data,client.deviceId,id)
                ui=ui.copy(busy=false,chat=ui.chat.accept(view,observation.issuedAtEpochSeconds))
                if(ui.chat.pendingId==null)check(prefs.edit().remove("chat_pending").commit())
                // A signed chat observation never refreshes status/task badges.
            } catch(cancelled:CancellationException) {
                ui=ui.copy(chat=ui.chat.uncertain("CHAT_INTERRUPTED_READBACK_ONLY"));throw cancelled
            } catch(_:SessionUnavailable) {
                ui=ui.sessionUnavailable().copy(busy=false,chat=ui.chat.uncertain("CHAT_SESSION_RECOVERY_REQUIRED"))
            } catch(error:Exception) {
                val code=error.message?.takeIf {Regex("[A-Z][A-Z0-9_]{1,100}").matches(it)} ?: "CHAT_READBACK_UNKNOWN"
                ui=ui.copy(busy=false,chat=ui.chat.uncertain(code))
            }
        }
        requestJob?.let {trackTransport(it,ticket)}
    }

    private fun request(op: () -> MobileObservation, apply: (JsonObject) -> Unit) {
        if (ui.busy || recoveryWork.busy) return
        val ticket=Any();recoveryWork.start(ticket)
        UsbReadback.clear(); generation = generation.invalidate("STALE")
        val epoch = generation.generation
        ui = ui.copy(freshness=generation,readbacks=ui.readbacks.invalidate(),busy=true,message=UiMessage(R.string.waiting_readback))
        requestJob = viewModelScope.launch {
            try {
                val observation = withContext(Dispatchers.IO) { transportMutex.withLock { owner().requireCurrent(); op().also { owner().requireCurrent() } } }
                if (generation.generation == epoch) {
                    val validUntilElapsedMs = observation.validUntilElapsedMs
                    generation = generation.accept(epoch,validUntilElapsedMs)
                    ui = ui.copy(freshness=generation,busy=false,connection="SIGNED_SESSION",lastSignedResponseAt=observation.issuedAtEpochSeconds)
                    apply(observation.data)
                    UsbReadback.accept(observation)
                    recordEvent(UiEventKind.SIGNED_READBACK,observation.issuedAtEpochSeconds)
                    viewModelScope.launch {
                        delay((validUntilElapsedMs-Freshness.elapsedMs()).coerceAtLeast(0)+1)
                        if (generation.generation == epoch) {
                            UsbReadback.clear(); generation = generation.invalidate("STALE")
                            ui = ui.copy(freshness=generation,connection="STALE",message=UiMessage(R.string.proof_expired))
                        }
                    }
                }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: StaleBindingOwner) {
                client.close()
                if (generation.generation == epoch) {
                    reconcileBinding()
                    ui = ui.copy(enrolled=false,busy=false,message=UiMessage(R.string.stale_owner))
                    recordEvent(UiEventKind.LOCAL_SESSION_LOST)
                }
            } catch (_: SessionUnavailable) {
                if (generation.generation == epoch) {
                    UsbReadback.clear(); generation = generation.invalidate("UNKNOWN")
                    ui = ui.sessionUnavailable().copy(freshness=generation,busy=false,connection="FRESH_ENROLLMENT_REQUIRED",
                        message=UiMessage(R.string.session_lost))
                    recordEvent(UiEventKind.LOCAL_SESSION_LOST)
                }
            } catch (_: Exception) {
                if (generation.generation == epoch) {
                    UsbReadback.clear(); generation = generation.invalidate("UNKNOWN")
                    ui = ui.copy(freshness=generation,busy=false,connection="OFFLINE_OR_DENIED",
                        message=UiMessage(R.string.unknown_notice))
                    recordEvent(UiEventKind.LOCAL_UNKNOWN)
                }
            }
        }
        requestJob?.let { trackTransport(it,ticket) }
    }
    fun connect(origin: String, tlsPin: String, hostKey: String, code: String) {
        if (ui.busy || recoveryWork.busy) return
        ui = ui.copy(enrolled=false,lastSignedResponseAt=null,task=null,missions=emptyList(),nextCursor=null,agentTask=null,
            agentMissions=emptyList(),providers=null,connection="UNVERIFIED")
        request({
            owner().requireCurrent()
            check(!ui.bindingInvalid) { "HOST_BINDING_INVALID" }
            val binding = owner().record?.host
            if (binding != null) {
                require(origin == binding.origin && tlsPin == binding.tlsPin && hostKey == binding.spki) { "HOST_BINDING_CHANGED" }
                client.preparePairing(binding)
            } else client.configure(origin,tlsPin,hostKey)
            client.enroll(code)
        }) {
            ui = ui.copy(enrolled=true,capabilities=client.capabilities,message=UiMessage(R.string.legacy_connected))
        }
    }
    fun status() = request({ client.status() },::acceptStatus)
    fun older() {
        val cursor = ui.nextCursor ?: return
        request({ client.statusPage(cursor) },::acceptStatus)
    }
    fun selectTask(taskId: String) {
        if(ui.busy || recoveryWork.busy || !supports("evidence"))return
        ui=ui.requestTask(taskId,false)
        request({ client.evidence(taskId) }) { acceptTask(it,taskId) }
    }
    fun retrySelectedReadback() {
        val selected=ui.requestedTask
        if(selected==null)status() else if(selected.agent)agentSelect(selected.id) else selectTask(selected.id)
    }
    private fun acceptStatus(data: JsonObject) {
        val missions = data.getValue("missions").jsonArray
        val current = ui.requestedTask?.takeUnless {it.agent}?.id ?: ui.task?.let { Wire.text(it,"task_id") }
        val selected = missions.map { it.jsonObject }.firstOrNull { current == null || Wire.text(it,"task_id") == current }
        ui = ui.copy(missions=missions.map { it.jsonObject },nextCursor=if(data["next_cursor"]==JsonNull) null else Wire.text(data,"next_cursor"))
        val visible = if(ui.requestedTask?.agent==false)selected else selected ?: missions.firstOrNull()?.jsonObject
        if (visible != null) acceptTask(visible) else ui = ui.copy(task=null,message=UiMessage(R.string.no_tasks))
    }
    fun preview(instruction: String) {
        if (!supports("preview") || ui.pending != null || !ui.freshness.isFresh() || !ui.enrolled || ui.busy) return
        val proposal = UUID.randomUUID().toString().replace("-","")
        // Opaque proposal ID only. Persist before the single POST; no token/code/content.
        if (!prefs.edit().putString("pending_proposal",proposal).commit()) return
        ui = ui.copy(pending=proposal)
        request({ client.preview(proposal,instruction) }) { data -> ui=ui.copy(requestedTask=null);acceptTask(data); clearPending() }
    }
    fun readback() {
        val proposal = ui.pending ?: return
        request({ client.readback(proposal) }) { data ->
            if (Wire.text(data,"state") == "UNKNOWN") {
                ui = ui.copy(message=UiMessage(R.string.unknown_reconcile))
            } else { ui=ui.copy(requestedTask=null);acceptTask(data); clearPending() }
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
                    message=UiMessage(R.string.id_retained))
            }
        } catch (_: Exception) { ui = ui.copy(message=UiMessage(R.string.id_failed)) }
    }
    private fun acceptTask(data: JsonObject, expectedId: String? = null) {
        ui = ui.observeTask(data,false,expectedId).copy(message=UiMessage(R.string.signed_state,listOf(Wire.text(data,"state"))))
    }
    fun evidence() {
        val task = ui.task ?: return
        selectTask(Wire.text(task,"task_id"))
    }
    fun stop() {
        val task = ui.task ?: return
        stop(task)
    }
    fun stop(reviewed: JsonObject) {
        val task = ui.task ?: return
        if (task!=reviewed || ui.taskStopReason(false)!=null) return
        request({ client.stop(Wire.text(task,"task_id")) }) { acceptTask(it,Wire.text(task,"task_id")) }
    }
    fun revoke() {
        if (ui.busy || recoveryWork.busy) return
        try {
            owner().requireCurrent()
            ui.pairing?.let { recoveryHints.pause(SessionRecovery.binding(it)) }
        } catch (_: Exception) {
            ui = ui.copy(message=UiMessage(R.string.connection_uncertain));return
        }
        request({ client.revoke() }) {
            client.close()
            UsbReadback.clear(); generation = generation.invalidate(); ui = MissionUi(freshness=generation,pending=ui.pending,archived=ui.archived,
                pendingAgent=ui.pendingAgent,archivedAgents=ui.archivedAgents,pairing=ui.pairing,
                connection="AUTO_RECOVERY_PAUSED",history=ui.history,message=UiMessage(R.string.session_revoked))
        }
    }
    fun agentStatus() = request({ client.agentStatus() }) { data ->
        ui = ui.copy(agentMissions=data.getValue("missions").jsonArray.map { it.jsonObject },
            message=UiMessage(R.string.agent_status))
    }
    fun agentProviders() = request({ client.agentProviders() }) { data -> ui = ui.copy(providers=data) }
    fun agentSelect(taskId: String) {
        if(ui.busy || recoveryWork.busy || !agentAvailable)return
        ui=ui.requestTask(taskId,true)
        request({ client.agentEvidence(taskId) }) { data -> acceptAgentTask(data,UiMessage(R.string.agent_view),taskId) }
    }
    private fun acceptAgentTask(data: JsonObject, message: UiMessage, expectedId: String? = null) {
        ui = ui.observeTask(data,true,expectedId).copy(message=message)
    }
    private fun proposeAgent(sourceTask: String? = null) {
        if (!agentAvailable || ui.pendingAgent != null || !ui.freshness.isFresh() || !ui.enrolled || ui.busy) return
        val proposal = UUID.randomUUID().toString().replace("-","")
        if (!prefs.edit().putString("pending_agent_proposal",proposal).commit()) return
        ui = ui.copy(pendingAgent=proposal)
        request({ client.agentProposal(proposal,sourceTask) }) { data ->
            ui=ui.copy(requestedTask=null)
            acceptAgentTask(data,UiMessage(R.string.needs_approval))
            prefs.edit().remove("pending_agent_proposal").apply();ui = ui.copy(pendingAgent=null)
        }
    }
    fun proposeSensorBridge() = proposeAgent()
    fun proposeGit() {
        val task = ui.agentTask ?: return
        proposeGit(task)
    }
    fun proposeGit(reviewed: JsonObject) {
        val task = ui.agentTask ?: return
        if (task!=reviewed || ui.gitPreviewReason()!=null) return
        proposeAgent(Wire.text(task,"task_id"))
    }
    fun agentReadback() {
        val proposal = ui.pendingAgent ?: return
        request({ client.agentReadback(proposal) }) { data ->
            if (data["task_id"] == null) ui = ui.copy(message=UiMessage(R.string.unknown_readback))
            else {
                ui=ui.copy(requestedTask=null)
                acceptAgentTask(data,UiMessage(R.string.proposal_readback))
                prefs.edit().remove("pending_agent_proposal").apply();ui = ui.copy(pendingAgent=null)
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
                    message=UiMessage(R.string.agent_id_retained))
            } else ui = ui.copy(message=UiMessage(R.string.agent_id_failed))
        } catch (_: Exception) { ui = ui.copy(message=UiMessage(R.string.agent_id_failed)) }
    }
    fun agentEvidence() {
        val task = ui.agentTask ?: return
        agentSelect(Wire.text(task,"task_id"))
    }
    fun agentStop() {
        val task = ui.agentTask ?: return
        agentStop(task)
    }
    fun agentStop(reviewed: JsonObject) {
        val task = ui.agentTask ?: return
        if (task!=reviewed || ui.taskStopReason(true)!=null) return
        request({ client.agentStop(Wire.text(task,"task_id")) }) { data ->
            acceptAgentTask(data,UiMessage(R.string.stop_observed),Wire.text(task,"task_id"))
        }
    }
    private fun recordEvent(kind: UiEventKind, at: Long = now()) {
        val task=ui.task?.takeIf { ui.readbacks.isFresh(it,false) }
            ?: ui.agentTask?.takeIf { ui.readbacks.isFresh(it,true) }
        val identity=task?.let { Wire.text(it,"task_id") }
        ui=ui.copy(history=appendUiHistory(ui.history,UiHistoryEvent(kind,at,identity)))
    }
    fun background() {
        UsbReadback.clear()
        foreground=false;recoveryWake.foreground(false)
        pairingJob?.cancel();requestJob?.cancel()
        UsbReadback.clear(); generation = generation.invalidate("STALE"); client.cancel()
        ui = ui.copy(freshness=generation,readbacks=ui.readbacks.invalidate(),busy=false,connection="STALE",message=UiMessage(R.string.resume_readback))
    }
    fun resume() {
        UsbReadback.clear()
        foreground=true;recoveryWake.foreground(true)
        try { reconcileBinding() }
        catch (_: Exception) { client.close(); ui = ui.copy(enrolled=false,bindingInvalid=true) }
        if(prefs.getString("chat_binding",null)==chatBinding()) {
            val pending=prefs.getString("chat_pending",null)?.takeIf {Wire.hex32.matches(it)}
            val thread=prefs.getString("chat_thread",null)?.takeIf {Wire.hex32.matches(it)}
            ui=ui.copy(chat=ui.chat.copy(threadId=thread,pendingId=pending,state=if(pending!=null) "UNKNOWN" else ui.chat.state))
        }
        UsbReadback.clear(); generation = generation.invalidate("STALE")
        ui = ui.copy(freshness=generation,readbacks=ui.readbacks.invalidate(),message=if (ui.pending == null) UiMessage(R.string.fresh_status) else
            UiMessage(R.string.unresolved_notice))
        if (!consumeUsbProvisioning()) automaticRecovery()
    }
    private fun consumeUsbProvisioning(): Boolean {
        if (BuildConfig.BUILD_TYPE!="cosmic4" || ui.busy || recoveryWork.busy || ui.bindingInvalid || owner().record!=null) return false
        return try {
            @Suppress("DEPRECATION")
            val signatures=getApplication<Application>().packageManager.getPackageInfo(
                getApplication<Application>().packageName,android.content.pm.PackageManager.GET_SIGNATURES).signatures!!
            require(signatures.size==1)
            val identity=UsbIdentity(getApplication<Application>().packageName,Wire.sha(signatures.single().toByteArray()),
                BuildConfig.AIOA_SOURCE_SHA,client.publicSpki)
            val transfer=androidUsbProvisioningStore(getApplication()).claim(identity,now()) ?: return false
            // Claim is durable BEFORE import/confirmHost. Any crash leaves readback, never another BEGIN.
            val archived=(ui.archived+transfer.archived).distinct().take(128)
            val agents=(ui.archivedAgents+transfer.archivedAgents).distinct().take(128)
            check(prefs.edit().putStringSet("unresolved_proposals",archived.toSet())
                .putStringSet("unresolved_agent_proposals",agents.toSet()).commit()) { "LOCAL_BINDING_SAVE_FAILED" }
            ui=ui.copy(archived=archived,archivedAgents=agents)
            check(importPacket(Wire.canonical(transfer.invite.envelope).toString(Charsets.UTF_8)))
            confirmHost()
            true
        } catch (_: Exception) {
            ui=ui.copy(connection="UNKNOWN",message=UiMessage(R.string.connection_uncertain))
            true
        }
    }
    override fun onCleared() { UsbReadback.clear(); network.close(); client.close(); super.onCleared() }
}
