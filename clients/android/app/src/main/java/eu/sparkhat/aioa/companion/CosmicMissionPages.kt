package eu.sparkhat.aioa.companion

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import kotlinx.serialization.json.*

/** Views consume existing verified state. Artwork never grants a capability. */
@Composable
internal fun CosmicMissionPage(page: String, model: MissionViewModel, navigate: (String) -> Unit) {
    val ui=model.ui
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement=Arrangement.spacedBy(16.dp)) {
        Text(stringResource(if(page=="home") R.string.cosmic_mission_control else pageLabel(page)),
            style=MaterialTheme.typography.headlineLarge,modifier=Modifier.semantics { heading() })
        Text(stringResource(R.string.cosmic_one_core),color=MaterialTheme.colorScheme.onSurfaceVariant)
        if (ui.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        ProofSummary(ui)
        when (page) {
            "home" -> {
                CosmicCard(stringResource(R.string.cosmic_quick_actions)) {
                    OutlinedButton(onClick={navigate("devices")},modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {
                        Text(stringResource(R.string.nav_devices))
                    }
                    Button(onClick=model::status,
                        enabled=ui.primaryDisabledReason(PrimaryAction.STATUS,System.currentTimeMillis()/1000)==null,
                        modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) { Text(stringResource(R.string.refresh_status)) }
                    OutlinedButton(onClick={navigate("missions")},modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {
                        Text(stringResource(R.string.cosmic_mission_results))
                    }
                    TextButton(onClick={navigate("activity")},modifier=Modifier.heightIn(min=48.dp)) {
                        Text(stringResource(R.string.nav_activity))
                    }
                }
                CosmicCard(stringResource(R.string.cosmic_muse_title)) {
                    Text(stringResource(R.string.chat_unavailable))
                    TextButton(onClick={navigate("chat")},modifier=Modifier.heightIn(min=48.dp)) {
                        Text(stringResource(R.string.nav_chat))
                    }
                }
            }
            "chat" -> {
                CosmicCard(stringResource(R.string.cosmic_muse_title)) {
                    Text(stringResource(R.string.cosmic_not_available),color=MaterialTheme.colorScheme.tertiary)
                    Text(stringResource(R.string.chat_unavailable))
                    OutlinedTextField(value="",onValueChange={},enabled=false,
                        label={Text(stringResource(R.string.cosmic_message))},modifier=Modifier.fillMaxWidth())
                    Button(onClick={},enabled=false,modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.cosmic_send)) }
                }
                Text(stringResource(R.string.cosmic_no_fake_chat))
            }
            "missions" -> MissionList(model,navigate)
            "details" -> MissionDetails(model)
            "critical" -> {
                CosmicCard(stringResource(R.string.cosmic_authority)) {
                    Text(stringResource(R.string.cosmic_owner_linux))
                    Text(stringResource(R.string.cosmic_no_write))
                    TextButton(onClick={navigate("approvals")},modifier=Modifier.heightIn(min=48.dp)) {
                        Text(stringResource(R.string.nav_approvals))
                    }
                    TextButton(onClick={navigate("details")},modifier=Modifier.heightIn(min=48.dp)) {
                        Text(stringResource(R.string.cosmic_review_stop))
                    }
                }
            }
            "repositories" -> {
                CosmicCard(stringResource(R.string.nav_repositories)) {
                    Text(stringResource(R.string.repositories_unavailable))
                    Text(stringResource(R.string.repositories_explanation))
                    if (ui.agentTask!=null) {
                        Text(stringResource(R.string.cosmic_fixture))
                        SelectionContainer { Text(ui.agentTask!!.display("git")) }
                    } else Text(stringResource(R.string.cosmic_no_git_evidence))
                }
            }
            "approvals" -> {
                CosmicCard(stringResource(R.string.cosmic_authority)) {
                    Text(stringResource(R.string.cosmic_owner_linux))
                    Text(stringResource(R.string.cosmic_approval_scope))
                    ui.pairing?.let { Text(stringResource(R.string.pairing_value,stringResource(ui.pairingLabel()))) }
                    TextButton(onClick={navigate("devices")},modifier=Modifier.heightIn(min=48.dp)) {
                        Text(stringResource(R.string.cosmic_view_pairing))
                    }
                }
                if (ui.pending!=null || ui.pendingAgent!=null || ui.archived.isNotEmpty() || ui.archivedAgents.isNotEmpty()) {
                    CosmicCard(stringResource(R.string.cosmic_unresolved)) {
                        SelectionContainer { Text((listOfNotNull(ui.pending,ui.pendingAgent)+ui.archived+ui.archivedAgents).joinToString("\n")) }
                        Text(stringResource(R.string.unknown_readback))
                        TextButton(onClick={navigate("missions")},modifier=Modifier.heightIn(min=48.dp)) {
                            Text(stringResource(R.string.cosmic_view_evidence))
                        }
                    }
                }
            }
            "activity" -> {
                CosmicCard(stringResource(R.string.nav_activity)) {
                    Text(stringResource(R.string.cosmic_session_activity))
                    Text(ui.message.localized())
                    if (ui.task!=null) SelectionContainer { Text(ui.task!!.display("task_id")+" · "+ui.task!!.display("state")) }
                    if (ui.agentTask!=null) SelectionContainer { Text(ui.agentTask!!.display("task_id")+" · "+ui.agentTask!!.display("state")) }
                    TextButton(onClick={navigate("details")},modifier=Modifier.heightIn(min=48.dp)) {
                        Text(stringResource(R.string.cosmic_view_evidence))
                    }
                }
            }
            "providers" -> {
                CosmicCard(stringResource(R.string.cosmic_muse_title)) {
                    Text(stringResource(R.string.cosmic_profile,ui.capabilities?.display("profile") ?: stringResource(R.string.no_host_proof)))
                    Text(stringResource(R.string.cosmic_providers_unavailable))
                    if (model.agentAvailable) {
                        Text(stringResource(R.string.cosmic_fixture))
                        Button(onClick=model::agentProviders,enabled=!ui.busy,modifier=Modifier.heightIn(min=48.dp)) {
                            Text(stringResource(R.string.cosmic_read_providers))
                        }
                    }
                    ui.providers?.let { SelectionContainer { Text(it.toString()) } }
                }
            }
        }
    }
}

@Composable
private fun ProofSummary(ui: MissionUi) {
    CosmicCard(stringResource(R.string.cosmic_connection)) {
        Text(stringResource(ui.connectionLabel()),style=MaterialTheme.typography.titleMedium,
            color=if(ui.enrolled && !ui.bindingInvalid && ui.freshness.isFresh()) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.tertiary)
        ui.pairing?.let { host ->
            SelectionContainer { Text(host.host.origin) }
            Text(stringResource(R.string.pairing_value,stringResource(ui.pairingLabel())))
        }
        Text(ui.message.localized())
        Text(ui.lastSignedResponseAt?.let { stringResource(R.string.last_signed_readback,formatSignedHostTime(it)) }
            ?: stringResource(R.string.no_signed_readback),style=MaterialTheme.typography.bodyMedium)
    }
}

@Composable
private fun MissionList(model: MissionViewModel, navigate: (String) -> Unit) {
    val ui=model.ui
    var instruction by rememberSaveable { mutableStateOf("") }
    val state=ui.task?.display("state") ?: "NONE"
    CosmicCard(stringResource(R.string.cosmic_mission_results)) {
        Text(stringResource(R.string.cosmic_missions_scope))
        if (!model.supports("preview")) Text(stringResource(R.string.cosmic_not_available),color=MaterialTheme.colorScheme.tertiary)
        OutlinedTextField(instruction,{if(it.toByteArray(Charsets.UTF_8).size<=2000) instruction=it},
            label={Text(stringResource(R.string.cosmic_instruction))},modifier=Modifier.fillMaxWidth(),
            enabled=model.supports("preview") && !ui.busy)
        Button(onClick={model.preview(instruction)},
            enabled=model.supports("preview") && !ui.busy && ui.freshness.isFresh() && instruction.isNotBlank() &&
                ui.pending==null && state !in setOf("PREVIEWED","RUNNING","LIVE_PENDING_AUTHORIZATION"),
            modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.cosmic_propose)) }
        if (ui.pending!=null) {
            Text(stringResource(R.string.unknown_readback))
            Button(onClick=model::readback,enabled=model.supports("preview") && !ui.busy,
                modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.cosmic_view_evidence)) }
        }
        if (ui.missions.isEmpty()) Text(stringResource(R.string.cosmic_no_missions))
        ui.missions.forEach { task ->
            val id=task.display("task_id")
            OutlinedButton(onClick={model.selectTask(id);navigate("details")},
                enabled=model.supports("evidence") && !ui.busy,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {
                Text(id+"\n"+task.display("state"))
            }
        }
        Button(onClick=model::older,enabled=ui.enrolled && !ui.busy && ui.nextCursor!=null,
            modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.cosmic_older)) }
    }
    if (model.agentAvailable) {
        CosmicCard(stringResource(R.string.cosmic_fixture)) {
            Text(stringResource(R.string.cosmic_offline_explanation))
            Button(onClick=model::agentStatus,enabled=!ui.busy,modifier=Modifier.heightIn(min=48.dp)) {
                Text(stringResource(R.string.cosmic_read_missions))
            }
            ui.agentMissions.forEach { task ->
                val id=task.display("task_id")
                OutlinedButton(onClick={model.agentSelect(id);navigate("details")},enabled=!ui.busy,
                    modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) { Text(id+"\n"+task.display("state")) }
            }
            if (ui.pendingAgent!=null) Button(onClick=model::agentReadback,enabled=!ui.busy,
                modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.cosmic_view_evidence)) }
        }
    }
}

@Composable
private fun MissionDetails(model: MissionViewModel) {
    val ui=model.ui
    val task=ui.task
    CosmicCard(stringResource(R.string.nav_details)) {
        Text(stringResource(R.string.cosmic_missions_scope))
        if (task==null) Text(stringResource(R.string.cosmic_no_missions))
        else {
            EvidenceFields(task)
            Button(onClick=model::evidence,enabled=model.supports("evidence") && !ui.busy,
                modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.cosmic_view_evidence)) }
            Button(onClick=model::stop,enabled=model.supports("stop") && !ui.busy && ui.freshness.canStop(task.display("state")),
                modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.cosmic_stop)) }
        }
    }
    ui.agentTask?.let { agent ->
        CosmicCard(stringResource(R.string.cosmic_fixture)) {
            Text(stringResource(R.string.cosmic_offline_explanation))
            EvidenceFields(agent)
            Button(onClick=model::agentEvidence,enabled=model.agentAvailable && !ui.busy,
                modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.cosmic_view_evidence)) }
            Button(onClick=model::agentStop,
                enabled=model.agentAvailable && !ui.busy && ui.freshness.canStop(agent.display("state")),
                modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.cosmic_stop)) }
        }
    }
}

@Composable
private fun EvidenceFields(value: JsonObject) {
    var expanded by rememberSaveable(value.display("task_id")) { mutableStateOf(false) }
    Text(stringResource(R.string.cosmic_retained_evidence),style=MaterialTheme.typography.bodyMedium)
    SelectionContainer {
        Column(verticalArrangement=Arrangement.spacedBy(12.dp)) {
            Text(value.display("task_id"),style=MaterialTheme.typography.labelSmall)
            Text(stringResource(R.string.cosmic_task_state,value.display("state")))
            Text(stringResource(R.string.cosmic_task_mode,value.display("mode")))
            Text(stringResource(R.string.cosmic_source,value.display("source_sha")),style=MaterialTheme.typography.bodyMedium)
            Text(stringResource(R.string.cosmic_task_digest,value.display("task_digest")),style=MaterialTheme.typography.bodyMedium)
            Text(stringResource(R.string.cosmic_capsule,value.display("capsule_digest")),style=MaterialTheme.typography.bodyMedium)
            if (value["model_id"]!=null) Text(stringResource(R.string.cosmic_model,value.display("model_id")))
            Text(stringResource(R.string.cosmic_receipt,value.display("receipt")),style=MaterialTheme.typography.bodyMedium)
        }
    }
    TextButton(onClick={expanded=!expanded},modifier=Modifier.heightIn(min=48.dp)) {
        Text(stringResource(if(expanded) R.string.cosmic_hide_artifacts else R.string.cosmic_show_artifacts))
    }
    if (expanded) SelectionContainer {
        Column(verticalArrangement=Arrangement.spacedBy(12.dp)) {
            for (key in listOf("plan","install_plan","files","diff","steps","tests","preview","operation","approval_status")) {
                value[key]?.takeUnless { it==JsonNull }?.let {
                    Text(key,style=MaterialTheme.typography.titleMedium)
                    Text(it.toString(),style=MaterialTheme.typography.bodyMedium)
                }
            }
        }
    }
}

private fun JsonObject.display(key: String): String =
    this[key]?.takeUnless { it==JsonNull }?.let { if(it is JsonPrimitive) it.content else it.toString() } ?: "—"
