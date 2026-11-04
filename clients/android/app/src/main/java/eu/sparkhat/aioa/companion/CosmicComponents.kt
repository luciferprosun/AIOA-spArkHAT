package eu.sparkhat.aioa.companion

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.colorResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import kotlinx.serialization.json.*

private val primaryPages=listOf("home","chat","missions","critical","repositories")
private val allPages=primaryPages+listOf("devices","approvals","details","activity","providers","recovery","settings")

/** Bars collapse around IME/short windows; the content retains its own scroll. */
@Composable
internal fun CosmicScaffold(page: String, navigate: (String)->Unit, content: @Composable ()->Unit) {
    val imeVisible=WindowInsets.ime.getBottom(LocalDensity.current)>0
    BoxWithConstraints(Modifier.fillMaxSize().safeDrawingPadding().imePadding()) {
        val short=maxHeight<420.dp
        Scaffold(contentWindowInsets=WindowInsets(0,0,0,0),
            topBar={ if(!imeVisible) CosmicTopBar(page,short,navigate) },
            bottomBar={ if(!imeVisible && !short) CosmicBottomNav(page,navigate) }) { padding ->
            Box(Modifier.fillMaxSize().padding(padding)) { content() }
        }
    }
}

@Composable
internal fun CosmicTopBar(page: String, compact: Boolean, navigate: (String)->Unit) {
    var menu by remember { mutableStateOf(false) }
    Surface(color=MaterialTheme.colorScheme.surface) {
        Row(Modifier.fillMaxWidth().heightIn(min=48.dp).padding(horizontal=16.dp),
            horizontalArrangement=Arrangement.spacedBy(8.dp)) {
            Text(stringResource(if(compact) pageLabel(page) else R.string.cosmic_brand),
                style=MaterialTheme.typography.titleMedium,color=MaterialTheme.colorScheme.primary,
                modifier=Modifier.weight(1f).padding(vertical=12.dp))
            Box {
                TextButton(onClick={menu=true},modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.master_more)) }
                DropdownMenu(expanded=menu,onDismissRequest={menu=false}) {
                    allPages.forEach { target ->
                        DropdownMenuItem(text={Text(stringResource(pageLabel(target)))},
                            modifier=Modifier.heightIn(min=48.dp).semantics { selected=page==target },
                            onClick={menu=false;navigate(target)})
                    }
                }
            }
        }
    }
}

@Composable
internal fun CosmicBottomNav(page: String, navigate: (String)->Unit) {
    Surface(color=MaterialTheme.colorScheme.surface) {
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal=8.dp),
            horizontalArrangement=Arrangement.spacedBy(4.dp)) {
            primaryPages.forEach { target ->
                TextButton(onClick={navigate(target)},contentPadding=PaddingValues(8.dp),
                    modifier=Modifier.widthIn(min=64.dp).heightIn(min=48.dp).semantics { selected=page==target }) {
                    Text(stringResource(pageLabel(target)),style=MaterialTheme.typography.labelSmall,
                        color=if(page==target) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@Composable
internal fun StatusChip(label: String, phase: CosmicPhase, historical: Boolean=false) {
    val tone=if(historical) MaterialTheme.colorScheme.onSurfaceVariant else when(phase) {
        CosmicPhase.SIGNED -> MaterialTheme.colorScheme.primary
        CosmicPhase.SUCCEEDED -> colorResource(R.color.cosmic_success)
        CosmicPhase.FAILED,CosmicPhase.REVOKED -> MaterialTheme.colorScheme.error
        CosmicPhase.PENDING,CosmicPhase.EXPIRED,CosmicPhase.UNKNOWN -> MaterialTheme.colorScheme.tertiary
        else -> MaterialTheme.colorScheme.onSurface
    }
    Surface(color=tone.copy(alpha=.12f),shape=RoundedCornerShape(12.dp)) {
        Text(label,color=tone,style=MaterialTheme.typography.labelLarge,modifier=Modifier.padding(horizontal=12.dp,vertical=8.dp))
    }
}

@Composable
internal fun ConnectionBanner(ui: MissionUi) {
    CosmicCard(stringResource(R.string.cosmic_connection)) {
        val fresh=ui.enrolled && !ui.bindingInvalid && ui.freshness.isFresh()
        StatusChip(stringResource(ui.connectionLabel()),if(fresh) CosmicPhase.SIGNED else CosmicPhase.UNKNOWN)
        ui.pairing?.let { SelectionContainer { Text(it.host.origin) };Text(stringResource(R.string.pairing_value,stringResource(ui.pairingLabel()))) }
        Text(ui.message.localized())
        Text(ui.lastSignedResponseAt?.let {stringResource(R.string.last_signed_readback,formatSignedHostTime(it))}
            ?: stringResource(R.string.no_signed_readback),style=MaterialTheme.typography.bodyMedium)
    }
}

@Composable
internal fun LoadingState() {
    LinearProgressIndicator(Modifier.fillMaxWidth())
    Text(stringResource(R.string.master_loading),style=MaterialTheme.typography.bodyMedium)
}

@Composable
internal fun ErrorState(message: String, onReadBack: (()->Unit)?=null) {
    CosmicCard(stringResource(R.string.state_unknown)) {
        Text(message,color=MaterialTheme.colorScheme.tertiary,modifier=Modifier.semantics { liveRegion=LiveRegionMode.Polite })
        if(onReadBack!=null) OutlinedButton(onClick=onReadBack,modifier=Modifier.heightIn(min=48.dp)) {
            Text(stringResource(R.string.master_read_only_retry))
        }
    }
}

@Composable
internal fun MissionCard(task: JsonObject, fresh: Boolean, enabled: Boolean, reason: Int?, onOpen: ()->Unit) {
    CosmicCard(task.display("task_id")) {
        StatusChip(stringResource(phaseResource(missionPhase(task))),missionPhase(task),historical=!fresh)
        if(task.display("mode")=="OFFLINE_FIXTURE") Text(stringResource(R.string.cosmic_fixture))
        Text(stringResource(if(fresh) R.string.master_current_task else R.string.master_task_historical))
        val steps=task["steps"] as? JsonArray
        if(steps!=null) Text(stringResource(R.string.master_steps_recorded,steps.size.toString()))
        if(fresh && missionPhase(task)==CosmicPhase.RUNNING) LinearProgressIndicator(Modifier.fillMaxWidth())
        OutlinedButton(onClick=onOpen,enabled=enabled,modifier=Modifier.heightIn(min=48.dp)) {Text(stringResource(R.string.master_open_task))}
        if(!enabled && reason!=null) Text(stringResource(reason),style=MaterialTheme.typography.bodyMedium)
    }
}

@Composable
internal fun ChatBubble(sender: String, text: String) {
    CosmicCard(sender) { SelectionContainer { Text(text) } }
}

@Composable
internal fun ProviderPicker(current: String?, disabledReason: Int) {
    OutlinedTextField(value=current ?: stringResource(R.string.cosmic_not_available),onValueChange={},enabled=false,
        readOnly=true,label={Text(stringResource(R.string.master_provider_label))},modifier=Modifier.fillMaxWidth())
    Text(stringResource(disabledReason),style=MaterialTheme.typography.bodyMedium)
}

@Composable
internal fun STOPButton(reason: Int?, onStop: ()->Unit) {
    Button(onClick=onStop,enabled=reason==null,modifier=Modifier.heightIn(min=48.dp),
        colors=ButtonDefaults.buttonColors(containerColor=MaterialTheme.colorScheme.error,contentColor=MaterialTheme.colorScheme.onError)) {
        Text(stringResource(R.string.cosmic_stop))
    }
    if(reason!=null) Text(stringResource(reason),style=MaterialTheme.typography.bodyMedium)
}

@Composable
internal fun ApprovalCard(title: String, id: String, busy: Boolean, archived: Boolean,
    onReadback: (()->Unit)?=null, onHandoff: (()->Unit)?=null) {
    var confirm by rememberSaveable(id,title) { mutableStateOf(false) }
    if(confirm && onHandoff!=null) AlertDialog(onDismissRequest={confirm=false},
        title={Text(stringResource(R.string.master_handoff_title))},
        text={Column(Modifier.heightIn(max=300.dp).verticalScroll(rememberScrollState())) {
            Text(title);SelectionContainer {Text(id)};Text(stringResource(R.string.master_handoff_body)) }},
        confirmButton={TextButton(enabled=!busy,onClick={confirm=false;onHandoff()}) {Text(stringResource(R.string.master_handoff))}},
        dismissButton={TextButton(onClick={confirm=false}) {Text(stringResource(R.string.cancel))}})
    CosmicCard(title) {
        SelectionContainer {Text(id,style=MaterialTheme.typography.labelSmall)}
        Text(stringResource(if(archived) R.string.master_handoff_body else R.string.unknown_readback))
        if(!archived) {
            OutlinedButton(onClick={onReadback?.invoke()},enabled=!busy && onReadback!=null,modifier=Modifier.heightIn(min=48.dp)) {
                Text(stringResource(R.string.cosmic_view_evidence))
            }
            if(onReadback==null) Text(stringResource(R.string.cosmic_not_available))
            OutlinedButton(onClick={confirm=true},enabled=!busy && onHandoff!=null,modifier=Modifier.heightIn(min=48.dp)) {
                Text(stringResource(R.string.master_handoff))
            }
        }
    }
}

@Composable
internal fun ReceiptPanel(task: JsonObject, readbacks: TaskReadbacks, agent: Boolean) {
    var expanded by rememberSaveable(task.display("task_id")) { mutableStateOf(false) }
    Text(stringResource(if(readbacks.isFresh(task,agent)) R.string.master_current_task else R.string.master_task_historical))
    readbacks.observedAt(task,agent)?.let { Text(stringResource(R.string.master_task_observed,formatSignedHostTime(it))) }
    SelectionContainer {
        Column(verticalArrangement=Arrangement.spacedBy(12.dp)) {
            Text(task.display("task_id"),style=MaterialTheme.typography.labelSmall)
            Text(stringResource(R.string.cosmic_task_state,task.display("state")))
            Text(stringResource(R.string.cosmic_task_mode,task.display("mode")))
            Text(stringResource(R.string.cosmic_source,task.display("source_sha")),style=MaterialTheme.typography.bodyMedium)
            Text(stringResource(R.string.cosmic_task_digest,task.display("task_digest")),style=MaterialTheme.typography.bodyMedium)
            Text(stringResource(R.string.cosmic_capsule,task.display("capsule_digest")),style=MaterialTheme.typography.bodyMedium)
            if(task["model_id"]!=null) Text(stringResource(R.string.cosmic_model,task.display("model_id")))
            if(task["receipt"]==null || task["receipt"]==JsonNull) Text(stringResource(R.string.master_receipt_missing))
            else Text(stringResource(R.string.cosmic_receipt,task.display("receipt")),style=MaterialTheme.typography.bodyMedium)
        }
    }
    TextButton(onClick={expanded=!expanded},modifier=Modifier.heightIn(min=48.dp)) {
        Text(stringResource(if(expanded) R.string.cosmic_hide_artifacts else R.string.cosmic_show_artifacts))
    }
    if(expanded) SelectionContainer {
        Column(verticalArrangement=Arrangement.spacedBy(12.dp)) {
            for(key in listOf("plan","install_plan","files","diff","steps","tests","preview","operation","approval_status")) {
                task[key]?.takeUnless {it==JsonNull}?.let { Text(key,style=MaterialTheme.typography.titleMedium);Text(it.toString()) }
            }
        }
    }
}

internal fun JsonObject.display(key: String): String =
    this[key]?.takeUnless {it==JsonNull}?.let {if(it is JsonPrimitive) it.content else it.toString()} ?: "—"
