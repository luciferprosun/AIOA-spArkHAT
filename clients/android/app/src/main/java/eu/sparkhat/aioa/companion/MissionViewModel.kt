package eu.sparkhat.aioa.companion

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*

data class MissionUi(
    val freshness: Freshness = Freshness(), val busy: Boolean = false, val enrolled: Boolean = false,
    val connection: String = "REMOTE_DEPLOYMENT_BLOCKED", val task: JsonObject? = null,
    val pending: String? = null, val archived: List<String> = emptyList(),
    val missions: List<JsonObject> = emptyList(), val nextCursor: String? = null,
    val message: String = "Wymagane HTTPS i nowy enrollment; owner NOT_BOUND."
)
fun MissionUi.sessionUnavailable() = copy(enrolled=false)

class MissionViewModel(app: Application) : AndroidViewModel(app) {
    private val prefs = app.getSharedPreferences("mobile-ui-v1",0)
    private val client = MobileClient(TransportIdentity())
    private var generation = Freshness()
    val publicSpki get() = client.publicSpki
    var ui by mutableStateOf(MissionUi(pending=prefs.getString("pending_proposal",null),
        archived=prefs.getStringSet("unresolved_proposals",emptySet())!!.filter { Wire.hex32.matches(it) }.sorted()))
        private set

    private fun request(op: () -> MobileObservation, apply: (JsonObject) -> Unit) {
        if (ui.busy) return
        generation = generation.invalidate("STALE")
        val epoch = generation.generation
        ui = ui.copy(freshness=generation,busy=true,message="Oczekiwanie na podpisany readback…")
        viewModelScope.launch {
            try {
                val observation = withContext(Dispatchers.IO) { op() }
                if (generation.generation == epoch) {
                    val validUntilElapsedMs = observation.validUntilElapsedMs
                    generation = generation.accept(epoch,validUntilElapsedMs)
                    ui = ui.copy(freshness=generation,busy=false,connection="SIGNED_SESSION")
                    apply(observation.data)
                    viewModelScope.launch {
                        delay((validUntilElapsedMs-Freshness.elapsedMs()).coerceAtLeast(0)+1)
                        if (generation.generation == epoch) {
                            generation = generation.invalidate("STALE")
                            ui = ui.copy(freshness=generation,connection="STALE",message="Dowód wygasł; pobierz podpisany GET/readback.")
                        }
                    }
                }
            } catch (_: SessionUnavailable) {
                if (generation.generation == epoch) {
                    generation = generation.invalidate("UNKNOWN")
                    ui = ui.sessionUnavailable().copy(freshness=generation,busy=false,connection="FRESH_ENROLLMENT_REQUIRED",
                        message="Sesja niedostępna; nowy enrollment wymagany. Pending/UNKNOWN pozostaje do readback lub rozliczenia na hoście.")
                }
            } catch (_: Exception) {
                if (generation.generation == epoch) {
                    generation = generation.invalidate("UNKNOWN")
                    ui = ui.copy(freshness=generation,busy=false,connection="OFFLINE_OR_DENIED",
                        message="UNKNOWN: odczytaj stan; nie ponawiaj POST. Sprawdź HTTPS, uprawnienia i czas sesji na hoście.")
                }
            }
        }
    }
    fun connect(origin: String, tlsPin: String, hostKey: String, code: String) {
        if (ui.busy) return
        ui = ui.copy(enrolled=false,task=null,missions=emptyList(),nextCursor=null,connection="UNVERIFIED")
        request({ client.configure(origin,tlsPin,hostKey); client.enroll(code) }) {
            ui = ui.copy(enrolled=true,message="Nowa sesja transportowa; owner NOT_BOUND. Pobierz status.")
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
        if (visible != null) acceptTask(visible) else ui = ui.copy(task=null,message="Brak własnych zadań na tej stronie.")
    }
    fun preview(instruction: String) {
        if (ui.pending != null || !ui.freshness.isFresh() || !ui.enrolled || ui.busy) return
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
                ui = ui.copy(message="UNKNOWN: propozycję musi rozliczyć operator na hoście; bez automatycznego retry.")
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
                    message="ID zachowany do rozliczenia na hoście. UNKNOWN w Core pozostaje bez zmian; żadnego retry ani efektu.")
            }
        } catch (_: Exception) { ui = ui.copy(message="Nie można zachować lokalnego ID; pending pozostaje zablokowany.") }
    }
    private fun acceptTask(data: JsonObject) {
        val previous = ui.task
        if (previous != null && Wire.text(previous,"task_id") == Wire.text(data,"task_id")) {
            require(Wire.text(previous,"task_digest") == Wire.text(data,"task_digest"))
        }
        ui = ui.copy(task=data,message="Podpisany stan: ${Wire.text(data,"state")}; model/browser LIVE niezweryfikowane.")
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
            message="Sesja odwołana; nowy enrollment wymagany.")
    }
    fun background() {
        generation = generation.invalidate("STALE"); client.cancel()
        ui = ui.copy(freshness=generation,busy=false,connection="STALE",message="Wznowienie wymaga podpisanego GET/readback.")
    }
    fun resume() {
        generation = generation.invalidate("STALE")
        ui = ui.copy(freshness=generation,message=if (ui.pending == null) "Pobierz świeży status." else
            "Nierozliczona propozycja: readback w tej samej sesji albo operator hosta po restarcie.")
    }
    override fun onCleared() { client.close(); super.onCleared() }
}
