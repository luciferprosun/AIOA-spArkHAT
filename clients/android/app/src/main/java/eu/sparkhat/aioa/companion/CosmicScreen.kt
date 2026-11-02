package eu.sparkhat.aioa.companion

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning

private val CosmicColors = darkColorScheme(
    background=Color(0xFF080D1C),surface=Color(0xFF13203B),primary=Color(0xFF63D9FF),
    secondary=Color(0xFFA58CF5),tertiary=Color(0xFFF1A75D),onBackground=Color(0xFFF4F7FF),
    onSurface=Color(0xFFF4F7FF),onPrimary=Color(0xFF080D1C),onSecondary=Color(0xFF080D1C))

/** Static layout: no decorative motion. Text wraps and all pages scroll at 200% font size. */
@Composable
internal fun CosmicApp(incomingPacket: String?, consumed: () -> Unit, model: MissionViewModel = viewModel()) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            when(event) {
                Lifecycle.Event.ON_STOP -> model.background()
                Lifecycle.Event.ON_RESUME -> model.resume()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer); onDispose { lifecycle.removeObserver(observer) }
    }
    var page by rememberSaveable { mutableStateOf("home") }
    LaunchedEffect(incomingPacket) {
        incomingPacket?.let { raw ->
            routePairingDelivery(raw,model::deliverPacket,showConfirmation={ page="home" },consumed=consumed)
        }
    }
    MaterialTheme(colorScheme=CosmicColors) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize().safeDrawingPadding().imePadding()) {
                // Two rows avoid clipped four-way navigation at accessibility font scales.
                listOf(listOf("home","missions"),listOf("repositories","settings")).forEach { row ->
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                        row.forEach { title ->
                            OutlinedButton(onClick={ page=title },modifier=Modifier.weight(1f).heightIn(min=48.dp)) {
                                Text(if(page == title) stringResource(R.string.selected_page,stringResource(pageLabel(title))) else stringResource(pageLabel(title)))
                            }
                        }
                    }
                }
                Box(Modifier.weight(1f)) {
                    if (page == "missions" || page == "advanced") LegacyMissionScreen(model,showConnection=page == "advanced")
                    else CosmicPage(page,model) { page="advanced" }
                }
            }
        }
    }
}

@Composable
private fun CosmicPage(page: String, model: MissionViewModel, advanced: () -> Unit) {
    val ui = model.ui
    val context = LocalContext.current
    var manual by remember { mutableStateOf(false) }
    var packet by remember { mutableStateOf("") }
    var diagnostics by remember { mutableStateOf(false) }
    var forget by remember { mutableStateOf(false) }
    if (forget) AlertDialog(onDismissRequest={ forget=false },title={ Text(stringResource(R.string.forget_title)) },
        text={ Text(stringResource(R.string.forget_explanation)) },
        confirmButton={ TextButton(onClick={ model.forgetHost(); forget=false }) { Text(stringResource(R.string.forget_confirm)) } },
        dismissButton={ TextButton(onClick={ forget=false }) { Text(stringResource(R.string.cancel)) } })
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),verticalArrangement=Arrangement.spacedBy(16.dp)) {
        Text(stringResource(R.string.app_name),style=MaterialTheme.typography.headlineLarge,modifier=Modifier.semantics { heading() })
        Text(stringResource(pageLabel(page)),style=MaterialTheme.typography.titleLarge)
        when(page) {
            "home" -> {
                Text(stringResource(R.string.home_title),style=MaterialTheme.typography.headlineSmall)
                Text(stringResource(R.string.connection_value,stateLabel(ui.connection)))
                Text(ui.message.localized())
                Button(enabled=!ui.busy,onClick={
                    try {
                        val options = GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
                        GmsBarcodeScanning.getClient(context,options).startScan()
                            .addOnSuccessListener { barcode ->
                                val raw = barcode.rawValue
                                if (raw == null) model.scannerMessage(R.string.scanner_empty) else model.importPacket(raw)
                            }
                            .addOnCanceledListener { model.scannerMessage(R.string.scanner_cancelled) }
                            .addOnFailureListener { model.scannerMessage(R.string.scanner_module); manual=true }
                    } catch (_: Exception) { manual=true; model.scannerMessage(R.string.scanner_unavailable) }
                },modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) { Text(stringResource(R.string.connect_action)) }
                Text(stringResource(R.string.scanner_explanation))
                TextButton(onClick={ manual=!manual },enabled=!ui.busy,modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.paste_action)) }
                if (manual) {
                    OutlinedTextField(packet,{ if(it.length<=22000) packet=it },label={ Text(stringResource(R.string.packet_label)) },modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
                    Button(onClick={ model.importPacket(packet); packet="" },enabled=!ui.busy && packet.isNotBlank(),modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.read_packet)) }
                }
                ui.invite?.let { invite ->
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
                            Text(stringResource(R.string.confirm_title),style=MaterialTheme.typography.titleLarge)
                            SelectionContainer { Text(invite.host.origin) }
                            Text(stringResource(R.string.confirm_explanation))
                            Button(onClick=model::confirmHost,enabled=!ui.busy,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) { Text(stringResource(R.string.confirm_action)) }
                        }
                    }
                }
                ui.pairing?.let { record ->
                    Text(stringResource(R.string.host_value,record.host.origin))
                    Text(stringResource(R.string.pairing_value,stateLabel(ui.pairingState)))
                    if (ui.pairingState in setOf("PENDING","APPROVED","BEGIN_UNCERTAIN","RECOVERY_REQUIRED")) {
                        val spokenCode = stringResource(R.string.sas_value,PairingProtocol.sas(record.requestDigest).toList().joinToString(" "))
                        SelectionContainer { Text(stringResource(R.string.sas_value,PairingProtocol.sas(record.requestDigest)),style=MaterialTheme.typography.headlineMedium,modifier=Modifier.semantics { contentDescription=spokenCode }) }
                        Text(stringResource(R.string.sas_explanation))
                    }
                    Button(onClick=model::readPairingStatus,enabled=!ui.busy && !ui.enrolled && System.currentTimeMillis()/1000 < record.expiresAt,
                        modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.read_pairing)) }
                    Button(onClick=model::reconnect,enabled=!ui.busy && (record.trusted || record.completeAttempted),modifier=Modifier.heightIn(min=48.dp)) {
                        Text(if(ui.pairingState == "CONNECTED") stringResource(R.string.refresh_connection) else stringResource(R.string.recover_session))
                    }
                }
                Button(onClick=model::status,enabled=ui.enrolled && !ui.busy,modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.refresh_status)) }
                Text(stringResource(R.string.chat_unavailable))
            }
            "repositories" -> {
                Text(stringResource(R.string.repositories_unavailable))
                Text(stringResource(R.string.repositories_explanation))
            }
            "settings" -> {
                Text(stringResource(R.string.trust_title),style=MaterialTheme.typography.titleLarge)
                Text(ui.message.localized())
                ui.pairing?.let { SelectionContainer { Text(stringResource(R.string.saved_host_value,it.host.origin)) } }
                Button(onClick=model::revoke,enabled=ui.enrolled && !ui.busy,modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.revoke_session)) }
                Text(stringResource(R.string.revoke_explanation))
                OutlinedButton(onClick={ forget=true },enabled=!ui.busy,modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.forget_action)) }
                Text(stringResource(R.string.motion_explanation))
                TextButton(onClick={ diagnostics=!diagnostics },modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.diagnostics)) }
                if (diagnostics) TextButton(onClick=advanced,modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.advanced_enrollment)) }
                if (diagnostics) SelectionContainer {
                    Column(verticalArrangement=Arrangement.spacedBy(12.dp)) {
                        Text(stringResource(R.string.device_value,model.publicSpki))
                        ui.pairing?.let {
                            Text(stringResource(R.string.host_diagnostics,it.host.spki,it.host.tlsPin,it.host.ownerScope,it.host.source,it.host.capsule,it.requestId,it.requestDigest))
                        }
                        Text(stringResource(R.string.capabilities_value,ui.capabilities?.toString() ?: stringResource(R.string.no_host_proof)))
                        Text(stringResource(R.string.storage_explanation))
                    }
                }
            }
        }
    }
}


@Composable
internal fun UiMessage.localized(): String = stringResource(resource,*arguments.toTypedArray())

internal fun pageLabel(page: String): Int = when(page) {
    "home" -> R.string.nav_home
    "missions" -> R.string.nav_missions
    "repositories" -> R.string.nav_repositories
    "settings" -> R.string.nav_settings
    else -> R.string.advanced_enrollment
}

@Composable
private fun stateLabel(state: String): String = stringResource(when(state) {
    "REMOTE_DEPLOYMENT_BLOCKED" -> R.string.state_deployment_blocked
    "DISCONNECTED" -> R.string.state_disconnected
    "STALE" -> R.string.state_stale
    "UNKNOWN","OFFLINE_OR_DENIED" -> R.string.state_unknown
    "UNVERIFIED" -> R.string.state_unverified
    "SIGNED_SESSION","CONNECTED" -> R.string.state_connected
    "FRESH_ENROLLMENT_REQUIRED","RECOVERY_REQUIRED" -> R.string.state_recovery
    "CONFIRM_HOST" -> R.string.state_confirm
    "PENDING" -> R.string.state_pending
    "APPROVED" -> R.string.state_approved
    "COMPLETED" -> R.string.state_completed
    "REVOKED" -> R.string.state_revoked
    "EXPIRED" -> R.string.state_expired
    "BEGIN_UNCERTAIN" -> R.string.state_begin_uncertain
    else -> R.string.state_unknown
})


/** A delivery event reveals accepted confirmation; ordinary recomposition never changes navigation. */
internal fun routePairingDelivery(raw: String, deliver: (String) -> Boolean,
    showConfirmation: () -> Unit, consumed: () -> Unit) {
    if (deliver(raw)) showConfirmation()
    consumed()
}
