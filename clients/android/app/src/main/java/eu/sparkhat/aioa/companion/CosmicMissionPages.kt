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

/** Every route uses the same verified ViewModel; unsupported ports stay explicit. */
@Composable
internal fun CosmicMissionPage(page: String, model: MissionViewModel, navigate: (String)->Unit) {
    val ui=model.ui
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
        verticalArrangement=Arrangement.spacedBy(16.dp)) {
        Text(stringResource(if(page=="home") R.string.cosmic_mission_control else pageLabel(page)),
            style=MaterialTheme.typography.headlineLarge,modifier=Modifier.semantics { heading() })
        Text(stringResource(R.string.cosmic_one_core),color=MaterialTheme.colorScheme.onSurfaceVariant)
        if(ui.busy) LoadingState()
        ConnectionBanner(ui)
        if(ui.connection in setOf("OFFLINE_OR_DENIED","FRESH_ENROLLMENT_REQUIRED","MANUAL_RECOVERY")) {
            val selected=ui.requestedTask
            val readable=if(selected==null)ui.enrolled else if(selected.agent)model.agentAvailable else model.supports("evidence")
            ErrorState(ui.message.localized(),if(readable && !ui.busy) ({model.retrySelectedReadback()}) else null)
        }
        when(page) {
            "home" -> {
                CosmicCard(stringResource(R.string.cosmic_quick_actions)) {
                    OutlinedButton(onClick={navigate("devices")},modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {
                        Text(stringResource(R.string.nav_devices))
                    }
                    val reason=ui.primaryDisabledReason(PrimaryAction.STATUS,System.currentTimeMillis()/1000)
                    Button(onClick=model::status,enabled=reason==null,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {
                        Text(stringResource(R.string.refresh_status))
                    }
                    if(reason!=null) Text(stringResource(reason))
                    OutlinedButton(onClick={navigate("missions")},modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) {
                        Text(stringResource(R.string.cosmic_mission_results))
                    }
                    TextButton(onClick={navigate("activity")},modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.nav_activity))}
                }
                CosmicCard(stringResource(R.string.cosmic_muse_title)) {
                    Text(stringResource(if(model.chatAvailable) R.string.chat_owner_gate else R.string.chat_native_unavailable))
                    TextButton(onClick={navigate("chat")},modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.nav_chat))}
                }
            }
            "chat" -> ChatPage(model)
            "missions" -> MissionList(model,navigate)
            "details" -> MissionDetails(model)
            "critical" -> CosmicCard(stringResource(R.string.cosmic_authority)) {
                Text(stringResource(R.string.cosmic_owner_linux))
                Text(stringResource(R.string.cosmic_no_write))
                OutlinedButton(onClick={navigate("approvals")},modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.nav_approvals))}
                OutlinedButton(onClick={navigate("details")},modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.cosmic_review_stop))}
            }
            "repositories" -> RepositoryPage(model)
            "approvals" -> ApprovalList(model,navigate)
            "activity" -> ActivityPage(ui)
            "providers" -> CosmicCard(stringResource(R.string.cosmic_muse_title)) {
                if(model.supports("chat")) {
                    Text("Meta Model API · muse-spark-1.3")
                    Text(stringResource(R.string.chat_owner_gate))
                    Text(stringResource(R.string.chat_ephemeral))
                    ui.chat.messages.lastOrNull {it.live}?.let {Text("LIVE receipt · ${it.requestId} · ${it.sourceSha}")}
                } else ProviderPicker(ui.agentTask?.display("provider_id"),R.string.master_provider_reason)
                Text(stringResource(R.string.cosmic_profile,ui.capabilities?.display("profile") ?: stringResource(R.string.no_host_proof)))
                if(!model.supports("chat")) Text(stringResource(R.string.cosmic_providers_unavailable))
                Button(onClick=model::agentProviders,enabled=model.agentAvailable && !ui.busy,modifier=Modifier.heightIn(min=48.dp)) {
                    Text(stringResource(R.string.cosmic_read_providers))
                }
                if(!model.agentAvailable) Text(stringResource(R.string.cosmic_not_available))
                ui.providers?.let {SelectionContainer {Text(it.toString())}}
            }
        }
    }
}

@Composable
private fun ChatPage(model: MissionViewModel) {
    val ui=model.ui
    var draft by rememberSaveable {mutableStateOf("")}
    CosmicCard(stringResource(R.string.cosmic_muse_title)) {
        Text("Meta · muse-spark-1.3",style=MaterialTheme.typography.titleMedium)
        Text(stringResource(if(model.chatAvailable) R.string.chat_owner_gate else R.string.chat_native_unavailable))
        Text(stringResource(R.string.chat_ephemeral))
        Text("${ui.chat.state} · ${ui.chat.lastSignedAt ?: "—"}")
        if(ui.chat.messages.isEmpty()) Text(stringResource(R.string.master_chat_history_empty))
        ui.chat.messages.forEach { message ->
            message.prompt?.let {ChatBubble(stringResource(R.string.chat_you),it)}
            message.reply?.let {ChatBubble("Muse Spark 1.3",it)}
            Text("${message.state} · ${message.requestId.take(12)} · ${message.sourceSha.take(12)}")
            message.receipt?.let {receipt ->
                Text("${stringResource(R.string.chat_estimate)} ${receipt["cost_estimate_usd"]?.jsonPrimitive?.content ?: "—"} USD")
                Text("SHA-256: ${receipt["response_sha256"]?.jsonPrimitive?.content ?: "—"}",style=MaterialTheme.typography.bodySmall)
            }
        }
        ui.chat.error?.let {Text(it,color=MaterialTheme.colorScheme.error)}
        OutlinedTextField(draft,{if(it.toByteArray(Charsets.UTF_8).size<=2000)draft=it},
            enabled=!ui.busy,label={Text(stringResource(R.string.cosmic_message))},modifier=Modifier.fillMaxWidth())
        Text("${draft.toByteArray(Charsets.UTF_8).size}/2000 B",style=MaterialTheme.typography.bodySmall)
        Button(onClick={model.chatSend(draft);draft=""},enabled=ui.chat.canSend(model.chatAvailable,model.supports("chat"),ui.busy,draft),
            modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.cosmic_send))}
        OutlinedButton(onClick=model::chatRefresh,enabled=model.chatAvailable && !ui.busy &&
            (ui.chat.pendingId!=null || ui.chat.threadId!=null),modifier=Modifier.heightIn(min=48.dp)) {
            Text(stringResource(R.string.chat_readback))
        }
        OutlinedButton(onClick=model::chatStop,enabled=model.chatAvailable && !ui.busy && ui.chat.pendingId!=null &&
            ui.chat.state in setOf("PENDING_OWNER","RUNNING"),modifier=Modifier.heightIn(min=48.dp)) {Text("STOP")}
        if(!ui.enrolled) OutlinedButton(onClick=model::reconnect,enabled=!ui.busy) {Text(stringResource(R.string.recover_session))}
    }
    if(draft.isNotBlank()) ChatBubble(stringResource(R.string.master_local_draft_bubble),draft)
}

@Composable
private fun MissionList(model: MissionViewModel, navigate: (String)->Unit) {
    val ui=model.ui
    var instruction by rememberSaveable {mutableStateOf("")}
    val currentState=ui.task?.display("state")
    val proposalReason=when {
        ui.busy -> R.string.reason_busy
        !model.supports("preview") -> R.string.master_proposal_unavailable
        !ui.freshness.isFresh() -> R.string.master_task_readback_required
        ui.pending!=null -> R.string.unknown_readback
        instruction.isBlank() -> R.string.master_instruction_required
        currentState in setOf("PREVIEWED","RUNNING","LIVE_PENDING_AUTHORIZATION") -> R.string.master_active_proposal
        else -> null
    }
    CosmicCard(stringResource(R.string.cosmic_mission_results)) {
        Text(stringResource(R.string.cosmic_missions_scope))
        OutlinedTextField(instruction,{if(it.toByteArray(Charsets.UTF_8).size<=2000)instruction=it},
            enabled=!ui.busy,label={Text(stringResource(R.string.cosmic_instruction))},modifier=Modifier.fillMaxWidth())
        Button(onClick={model.preview(instruction)},enabled=proposalReason==null,modifier=Modifier.heightIn(min=48.dp)) {
            Text(stringResource(R.string.cosmic_propose))
        }
        if(proposalReason!=null) Text(stringResource(proposalReason))
        OutlinedButton(onClick={navigate("approvals")},modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.nav_approvals))}
    }
    if(ui.missions.isEmpty()) Text(stringResource(R.string.cosmic_no_missions))
    ui.missions.forEach {task ->
        MissionCard(task,ui.readbacks.isFresh(task,false),model.supports("evidence") && !ui.busy,
            if(ui.busy)R.string.reason_busy else R.string.cosmic_not_available,
            onOpen={model.selectTask(task.display("task_id"));navigate("details")})
    }
    if(ui.nextCursor!=null) OutlinedButton(onClick=model::older,enabled=ui.enrolled && !ui.busy,
        modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.cosmic_older))}
    CosmicCard(stringResource(R.string.master_propose_sensor)) {
        Text(stringResource(R.string.cosmic_offline_explanation))
        val reason=when {
            ui.busy -> R.string.reason_busy
            !model.agentAvailable -> R.string.master_proposal_unavailable
            !ui.freshness.isFresh() -> R.string.master_task_readback_required
            ui.pendingAgent!=null -> R.string.master_pending_agent
            else -> null
        }
        Button(onClick=model::proposeSensorBridge,enabled=reason==null,modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.master_propose_sensor))}
        if(reason!=null) Text(stringResource(reason))
        OutlinedButton(onClick=model::agentStatus,enabled=model.agentAvailable && !ui.busy,modifier=Modifier.heightIn(min=48.dp)) {
            Text(stringResource(R.string.cosmic_read_missions))
        }
        if(!model.agentAvailable) Text(stringResource(R.string.cosmic_not_available))
    }
    ui.agentMissions.forEach {task ->
        MissionCard(task,ui.readbacks.isFresh(task,true),model.agentAvailable && !ui.busy,
            if(ui.busy)R.string.reason_busy else R.string.cosmic_not_available,
            onOpen={model.agentSelect(task.display("task_id"));navigate("details")})
    }
}

@Composable
private fun MissionDetails(model: MissionViewModel) {
    val ui=model.ui
    val task=ui.detailTask(false)
    ui.requestedTask?.let {selected ->
        CosmicCard(stringResource(R.string.master_requested_task)) {
            SelectionContainer {Text(selected.id)}
            if(ui.detailTask(selected.agent)==null)Text(stringResource(R.string.master_selected_task_pending))
            val readable=if(selected.agent)model.agentAvailable else model.supports("evidence")
            OutlinedButton(onClick=model::retrySelectedReadback,enabled=readable && !ui.busy,modifier=Modifier.heightIn(min=48.dp)) {
                Text(stringResource(R.string.master_read_only_retry))
            }
            if(!readable)Text(stringResource(R.string.cosmic_not_available))
        }
    }
    CosmicCard(stringResource(R.string.nav_details)) {
        Text(stringResource(R.string.cosmic_missions_scope))
        if(task==null) Text(stringResource(R.string.cosmic_no_missions)) else {
            Text(task.display("task_id"),style=MaterialTheme.typography.labelSmall)
            StatusChip(stringResource(phaseResource(missionPhase(task))),missionPhase(task),!ui.readbacks.isFresh(task,false))
            STOPButton(ui.taskStopReason(false)) {model.stop(task)}
            OutlinedButton(onClick={model.selectTask(task.display("task_id"))},
                enabled=model.supports("evidence") && !ui.busy,modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.cosmic_view_evidence))}
            if(!model.supports("evidence")) Text(stringResource(R.string.cosmic_not_available))
            ReceiptPanel(task,ui.readbacks,false)
        }
    }
    ui.detailTask(true)?.let {agent ->
        CosmicCard(stringResource(R.string.cosmic_fixture)) {
            Text(agent.display("task_id"),style=MaterialTheme.typography.labelSmall)
            Text(stringResource(R.string.cosmic_offline_explanation))
            StatusChip(stringResource(phaseResource(missionPhase(agent))),missionPhase(agent),!ui.readbacks.isFresh(agent,true))
            STOPButton(ui.taskStopReason(true)) {model.agentStop(agent)}
            OutlinedButton(onClick={model.agentSelect(agent.display("task_id"))},enabled=model.agentAvailable && !ui.busy,
                modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.cosmic_view_evidence))}
            if(!model.agentAvailable) Text(stringResource(R.string.cosmic_not_available))
            ReceiptPanel(agent,ui.readbacks,true)
        }
    }
}

@Composable
private fun RepositoryPage(model: MissionViewModel) {
    val ui=model.ui
    val task=ui.detailTask(true)
    CosmicCard(stringResource(R.string.nav_repositories)) {
        Text(stringResource(R.string.repositories_unavailable))
        Text(stringResource(R.string.repositories_explanation))
        val reason=ui.gitPreviewReason()
        Button(onClick={if(task!=null) model.proposeGit(task)},enabled=reason==null,modifier=Modifier.heightIn(min=48.dp)) {
            Text(stringResource(R.string.master_git_preview))
        }
        if(reason!=null) Text(stringResource(reason))
        Text(stringResource(R.string.master_git_no_write))
        if(task!=null) {
            Text(stringResource(R.string.cosmic_fixture))
            Text(stringResource(if(ui.readbacks.isFresh(task,true)) R.string.master_current_task else R.string.master_task_historical))
            SelectionContainer {Text(task.display("git"))}
            OutlinedButton(onClick={model.agentSelect(task.display("task_id"))},enabled=model.agentAvailable && !ui.busy,
                modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.cosmic_view_evidence))}
        } else Text(stringResource(R.string.cosmic_no_git_evidence))
    }
}

@Composable
private fun ApprovalList(model: MissionViewModel,navigate: (String)->Unit) {
    val ui=model.ui
    CosmicCard(stringResource(R.string.cosmic_authority)) {
        Text(stringResource(R.string.cosmic_owner_linux))
        Text(stringResource(R.string.cosmic_approval_scope))
        ui.pairing?.let {Text(stringResource(R.string.pairing_value,stringResource(ui.pairingLabel())))}
        TextButton(onClick={navigate("devices")},modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.cosmic_view_pairing))}
    }
    ui.pending?.let {id ->
        ApprovalCard(stringResource(R.string.master_document_pending),id,ui.busy,false,
            onReadback=if(model.supports("preview")) ({if(model.ui.pending==id)model.readback()}) else null,
            onHandoff={if(model.ui.pending==id)model.archivePendingHint()})
    }
    ui.pendingAgent?.let {id ->
        ApprovalCard(stringResource(R.string.master_agent_pending),id,ui.busy,false,
            onReadback=if(model.agentAvailable) ({if(model.ui.pendingAgent==id)model.agentReadback()}) else null,
            onHandoff={if(model.ui.pendingAgent==id)model.archivePendingAgentHint()})
    }
    ui.archived.forEach {id -> ApprovalCard(stringResource(R.string.master_document_archived),id,ui.busy,true)}
    ui.archivedAgents.forEach {id -> ApprovalCard(stringResource(R.string.master_agent_archived),id,ui.busy,true)}
}

@Composable
private fun ActivityPage(ui: MissionUi) {
    Text(stringResource(R.string.master_history_scope))
    if(ui.history.isEmpty()) Text(stringResource(R.string.master_history_empty))
    ui.history.asReversed().forEach {event ->
        CosmicCard(stringResource(when(event.kind) {
            UiEventKind.SIGNED_READBACK -> R.string.master_history_signed
            UiEventKind.LOCAL_UNKNOWN -> R.string.master_history_unknown
            UiEventKind.LOCAL_SESSION_LOST -> R.string.master_history_session
        })) {
            Text(formatSignedHostTime(event.atEpochSeconds),style=MaterialTheme.typography.labelSmall)
            event.taskId?.let {SelectionContainer {Text(it)}}
        }
    }
}
