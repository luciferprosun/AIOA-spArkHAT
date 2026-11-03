package eu.sparkhat.aioa.companion

import android.os.Bundle
import android.content.Intent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.serialization.json.*

class MainActivity : ComponentActivity() {
    private var incomingPacket by mutableStateOf<String?>(null)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) consumePairingIntent(intent)
        setContent { CosmicApp(incomingPacket,consumed={ incomingPacket = null }) }
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        consumePairingIntent(intent)
    }
    private fun consumePairingIntent(delivery: Intent?) {
        incomingPacket = delivery?.takeIf { it.action == Intent.ACTION_VIEW }?.dataString
        // Clear Activity's retained intent immediately: recreation cannot replay a consumed VIEW.
        setIntent(Intent(delivery ?: Intent()).apply { data = null; action = Intent.ACTION_MAIN })
    }
}

@Composable
internal fun LegacyMissionScreen(model: MissionViewModel, showConnection: Boolean = false) {
    val ui = model.ui
    var origin by remember { mutableStateOf("") }
    var tlsPin by remember { mutableStateOf("") }
    var hostKey by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var instruction by remember { mutableStateOf("Summarize the public test document.") }
    var archiveDialog by remember { mutableStateOf(false) }
    var archiveAgentDialog by remember { mutableStateOf(false) }
    if (archiveDialog && ui.pending != null) AlertDialog(
        onDismissRequest={ archiveDialog=false },
        title={ Text("Hand off the ID for host reconciliation") },
        text={ Column(Modifier.heightIn(max=300.dp).verticalScroll(rememberScrollState())) {
            Text("Only the local UI hint changes. Core UNKNOWN stays UNKNOWN. No retry, STOP or approval is sent. The ID remains available for host reconciliation. A new proposal still requires Core and exact host approval.")
        } },
        confirmButton={ TextButton(onClick={ model.archivePendingHint(); archiveDialog=false }) { Text("Keep unresolved ID") } },
        dismissButton={ TextButton(onClick={ archiveDialog=false }) { Text("Cancel") } }
    )
    if (archiveAgentDialog && ui.pendingAgent != null) AlertDialog(
        onDismissRequest={ archiveAgentDialog=false },
        title={ Text("Hand off the agent ID to the host") },
        text={ Column(Modifier.heightIn(max=300.dp).verticalScroll(rememberScrollState())) {
            Text("Keep this unresolved ID for host reconciliation after session loss. Core UNKNOWN stays UNKNOWN. No retry, STOP or approval is sent. Only the local proposal block is cleared after the ID is saved. A new proposal requires a fresh session and exact host approval.")
        } },
        confirmButton={ TextButton(onClick={ model.archivePendingAgentHint(); archiveAgentDialog=false }) { Text("Keep unresolved agent ID") } },
        dismissButton={ TextButton(onClick={ archiveAgentDialog=false }) { Text("Cancel") } }
    )
    Column(Modifier.fillMaxSize().safeDrawingPadding().imePadding().verticalScroll(rememberScrollState())
        .padding(16.dp), verticalArrangement=Arrangement.spacedBy(12.dp)) {
        Text("AIOA spArkHAT",style=MaterialTheme.typography.headlineMedium)
        Text("METAGuardiansSPARK • Tasks / Mission Control")
        Text("Muse (Meta Model API) • host-side • LIVE unverified")
        Text("Connection: ${ui.connection} • ${ui.freshness.state}")
        Text("Pairing: transport ${if(ui.enrolled) "session" else "none"} • owner NOT_BOUND")
        Text("Billing Unverified • phone cannot approve spending")
        Text(ui.message.localized())
        HorizontalDivider()
        if (showConnection) {
        Text("Connection and fresh enrollment",style=MaterialTheme.typography.titleMedium)
        OutlinedTextField(origin,{ origin=it },label={ Text("Exact Linux HTTPS origin") },modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
        OutlinedTextField(tlsPin,{ tlsPin=it },label={ Text("Separate TLS SPKI pin: sha256/…") },modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
        OutlinedTextField(hostKey,{ hostKey=it },label={ Text("Independent host identity SPKI (Base64 DER)") },modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
        Text("New device public key — compare locally on the host:")
        SelectionContainer { Text(model.publicSpki) }
        OutlinedTextField(code,{ code=it },label={ Text("One-time code, at most 5 minutes") },
            visualTransformation=PasswordVisualTransformation(),modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
        Button(enabled=!ui.busy && code.isNotEmpty(),onClick={
            model.connect(origin,tlsPin,hostKey,code); code=""
        }) { Text(if(ui.enrolled) "Re-enroll and revoke the old session" else "Verify host and enroll transport") }
        Button(enabled=ui.enrolled && !ui.busy,onClick=model::status) { Text("Signed status / readback") }
        Button(enabled=ui.enrolled && !ui.busy,onClick=model::revoke) { Text("Revoke this session") }
        HorizontalDivider()
        }
        Text("Agent workspace",style=MaterialTheme.typography.titleMedium)
        if (!model.agentAvailable) Text(androidx.compose.ui.res.stringResource(R.string.agent_unavailable))
        Text("One Linux Core. Phone proposes and observes; exact approval remains on the host.")
        Button(enabled=model.agentAvailable && !ui.busy,onClick=model::agentStatus) { Text("Signed agent status") }
        Button(enabled=model.agentAvailable && !ui.busy,onClick=model::agentProviders) { Text("Provider choices / evidence") }
        ui.providers?.get("providers")?.jsonArray?.forEach { item ->
            val provider = item.jsonObject
            Text("${Wire.text(provider,"provider_id")} / ${Wire.text(provider,"model_id")} — ${Wire.text(provider,"availability")}")
        }
        Button(enabled=model.agentAvailable && !ui.busy && ui.freshness.isFresh() && ui.pendingAgent==null,
            onClick=model::proposeSensorBridge) { Text("Propose SensorBridge + tests + README") }
        Button(enabled=model.agentAvailable && !ui.busy && ui.pendingAgent!=null,onClick=model::agentReadback) {
            Text("Read back pending agent proposal")
        }
        ui.pendingAgent?.let { SelectionContainer { Text("Pending ID: $it — no automatic retry") } }
        Button(enabled=!ui.busy && ui.pendingAgent!=null,onClick={ archiveAgentDialog=true }) {
            Text("Keep agent ID for the host operator")
        }
        if (ui.archivedAgents.isNotEmpty()) SelectionContainer {
            Text("Unresolved agent IDs — host reconciliation, Core unchanged:\n"+ui.archivedAgents.joinToString("\n"))
        }
        ui.agentMissions.forEach { item ->
            val id = Wire.text(item,"task_id")
            OutlinedButton(enabled=model.agentAvailable && !ui.busy,onClick={ model.agentSelect(id) }) {
                Text(id.take(15)+"… • "+Wire.text(item,"state"))
            }
        }
        ui.agentTask?.let { agent ->
            val agentState = Wire.text(agent,"state")
            SelectionContainer { Column(verticalArrangement=Arrangement.spacedBy(6.dp)) {
                Text("Task: ${Wire.text(agent,"task_id")} • $agentState")
                Text("${Wire.text(agent,"provider_id")} / ${Wire.text(agent,"model_id")} • ${Wire.text(agent,"mode")}")
                Text("Source: ${Wire.text(agent,"source_sha")}\nTask digest: ${Wire.text(agent,"task_digest")}")
                Text("Approval: ${Wire.text(agent,"approval_status")}")
                Text("Steps: ${agent["steps"]}\nTests: ${agent["tests"]}")
                Text("Files / diff: ${agent["diff"]}\nDependency plan: ${agent["install_plan"]}")
                Text("Git branch / commit / PR preview: ${agent["git"]}")
                Text("Receipt: ${agent["receipt"] ?: JsonNull}")
            } }
            val files = agent.getValue("files").jsonObject
            files.forEach { (name, value) ->
                Text(name,style=MaterialTheme.typography.titleSmall)
                SelectionContainer { Text(Wire.text(value.jsonObject,"text")) }
            }
            Button(enabled=model.agentAvailable && !ui.busy,onClick=model::agentEvidence) { Text("Signed readback") }
            Button(enabled=model.agentAvailable && !ui.busy && ui.freshness.canStop(agentState),onClick=model::agentStop) { Text("STOP agent task") }
            val sourceOperation = Wire.text(agent.getValue("operation").jsonObject,"operation_class")
            Button(enabled=model.agentAvailable && !ui.busy && ui.freshness.isFresh() && ui.pendingAgent==null &&
                agentState=="AGENT_COMPLETED" && sourceOperation=="SANDBOX_EXEC",onClick=model::proposeGit) {
                Text("Preview local commit of verified files")
            }
            Text("Install / remote push / PR / owner approval: disabled on this phone.")
        }
        HorizontalDivider()
        Text("Document mission • OFFLINE / LIVE",style=MaterialTheme.typography.titleMedium)
        Text("Preview is a proposal. Run/approval stays on the trusted host. LIVE is blocked.")
        OutlinedTextField(instruction,{ if(it.toByteArray().size<=2000) instruction=it },label={ Text("Instruction") },
            modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
        val task = ui.task
        val state = task?.let { Wire.text(it,"state") } ?: "NONE"
        Button(enabled=model.supports("preview") && !ui.busy && ui.freshness.isFresh() && ui.pending==null &&
            state !in setOf("PREVIEWED","RUNNING","LIVE_PENDING_AUTHORIZATION"),onClick={ model.preview(instruction) }) { Text("Preview") }
        Button(enabled=model.supports("preview") && !ui.busy && ui.pending!=null,onClick=model::readback) { Text("Read back unresolved proposal") }
        Button(enabled=!ui.busy && ui.pending!=null,onClick={ archiveDialog=true }) { Text("Keep unresolved ID for the operator") }
        if (ui.archived.isNotEmpty()) SelectionContainer {
            Text("Unresolved local IDs — host operator, no Core state change:\n"+ui.archived.joinToString("\n"))
        }
        if (ui.missions.isNotEmpty()) {
            Text("Your tasks — up to 16 per page; signed GET for older tasks")
            ui.missions.forEach { item ->
                val id = Wire.text(item,"task_id")
                OutlinedButton(enabled=model.supports("evidence") && !ui.busy,onClick={ model.selectTask(id) },modifier=Modifier.fillMaxWidth()) {
                    Text(id.take(15)+"… • "+Wire.text(item,"state"))
                }
            }
        }
        Button(enabled=ui.enrolled && !ui.busy && ui.nextCursor!=null,onClick=model::older) { Text("Older tasks") }
        if (task != null) {
            SelectionContainer { Column {
                Text("Task: ${Wire.text(task,"task_id")}")
                Text("State: $state • mode: ${Wire.text(task,"mode")}")
                Text("Source SHA: ${Wire.text(task,"source_sha")}")
                Text("Task digest: ${Wire.text(task,"task_digest")}")
                Text("Capsule: ${Wire.text(task,"capsule_digest")}")
                Text("Last Receipt: ${if(task["receipt"]==JsonNull) "none / unknown" else task["receipt"].toString()}")
            } }
        } else Text("Last receipt: none; no execution evidence")
        Button(enabled=model.supports("evidence") && !ui.busy && task!=null,onClick=model::evidence) { Text("Evidence") }
        Button(enabled=model.supports("stop") && !ui.busy && ui.freshness.canStop(state),onClick=model::stop) { Text("STOP your mission") }
        Text("Chat: Not yet available in this bounded profile.")
        Text("Transport does not grant owner pairing. Reinstallation requires fresh enrollment.")
    }
}
