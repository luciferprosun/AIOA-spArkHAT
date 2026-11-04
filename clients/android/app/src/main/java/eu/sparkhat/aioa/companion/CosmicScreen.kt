package eu.sparkhat.aioa.companion

import androidx.compose.foundation.layout.*
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import kotlinx.coroutines.delay
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
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
    val savedPages=rememberSaveableStateHolder()
    val imeVisible=WindowInsets.ime.getBottom(LocalDensity.current)>0
    val focus=LocalFocusManager.current
    val keyboard=LocalSoftwareKeyboardController.current
    BackHandler(enabled=page!="home" && !imeVisible) { page="home" }
    LaunchedEffect(incomingPacket) {
        incomingPacket?.let { raw ->
            routePairingDelivery(raw,model::deliverPacket,showConfirmation={ page="devices" },consumed=consumed)
        }
    }
    CosmicTheme {
        CosmicScaffold(page,navigate={ target -> focus.clearFocus();keyboard?.hide();page=target }) {
            savedPages.SaveableStateProvider(page) {
                when(page) {
                    "devices","recovery","settings" -> CosmicPage(page,model) {page="advanced"}
                    "advanced" -> LegacyMissionScreen(model,showConnection=true)
                    else -> CosmicMissionPage(page,model) {target -> focus.clearFocus();keyboard?.hide();page=target}
                }
            }
        }
    }
}

@Composable
private fun CosmicPage(page: String, model: MissionViewModel, advanced: () -> Unit) {
    val ui = model.ui
    val context = LocalContext.current
    val focusManager = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    // Used only for invitation expiry controls, never as the displayed host response time.
    var expiryRefresh by remember { mutableIntStateOf(0) }
    val nowSeconds = remember(ui,expiryRefresh) { System.currentTimeMillis()/1000 }
    val nextExpiry = listOfNotNull(ui.invite?.expiresAt,ui.pairing?.expiresAt).filter { it > nowSeconds }.minOrNull()
    LaunchedEffect(nextExpiry) {
        if (nextExpiry != null) {
            delay((nextExpiry-nowSeconds)*1000+1)
            expiryRefresh++
        }
    }
    val connectReason = ui.primaryDisabledReason(PrimaryAction.CONNECT,nowSeconds)
    val confirmReason = ui.primaryDisabledReason(PrimaryAction.CONFIRM,nowSeconds)
    val pairingStatusReason = ui.primaryDisabledReason(PrimaryAction.PAIRING_STATUS,nowSeconds)
    val reconnectReason = ui.primaryDisabledReason(PrimaryAction.RECONNECT,nowSeconds)
    val statusReason = ui.primaryDisabledReason(PrimaryAction.STATUS,nowSeconds)
    var manual by rememberSaveable { mutableStateOf(false) }
    var packet by rememberSaveable { mutableStateOf("") }
    var diagnostics by rememberSaveable { mutableStateOf(false) }
    var forget by remember { mutableStateOf(false) }
    LaunchedEffect(ui.invite) {
        if (ui.invite != null) {
            manual = false
            packet = ""
            focusManager.clearFocus()
            keyboard?.hide()
        }
    }
    if (forget) AlertDialog(onDismissRequest={ forget=false },title={ Text(stringResource(R.string.forget_title)) },
        text={ Text(stringResource(R.string.forget_explanation)) },
        confirmButton={ TextButton(onClick={ model.forgetHost(); forget=false }) { Text(stringResource(R.string.forget_confirm)) } },
        dismissButton={ TextButton(onClick={ forget=false }) { Text(stringResource(R.string.cancel)) } })
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),verticalArrangement=Arrangement.spacedBy(16.dp)) {
        Text(stringResource(pageLabel(page)),style=MaterialTheme.typography.headlineLarge,modifier=Modifier.semantics { heading() })
        when(page) {
            "devices","recovery" -> {
                Text(stringResource(R.string.home_title),style=MaterialTheme.typography.headlineSmall)
                Text(stringResource(R.string.connection_value,stringResource(ui.connectionLabel())))
                Text(ui.message.localized())
                Text(ui.lastSignedResponseAt?.let { stringResource(R.string.last_signed_readback,formatSignedHostTime(it)) }
                    ?: stringResource(R.string.no_signed_readback))
                Button(enabled=connectReason == null,onClick={
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
                DisabledReason(connectReason)
                Text(stringResource(R.string.scanner_explanation))
                TextButton(onClick={ manual=!manual },enabled=connectReason == null,modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.paste_action)) }
                if (manual) {
                    OutlinedTextField(packet,{ if(it.length<=22000) packet=it },label={ Text(stringResource(R.string.packet_label)) },modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
                    val packetReason = connectReason ?: if(packet.isBlank()) R.string.reason_packet_required else null
                    Button(onClick={ model.importPacket(packet); packet="" },enabled=packetReason == null,modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.read_packet)) }
                    DisabledReason(packetReason)
                }
                ui.invite?.let { invite ->
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
                            Text(stringResource(R.string.confirm_title),style=MaterialTheme.typography.titleLarge)
                            SelectionContainer { Text(invite.host.origin) }
                            SelectionContainer { Text(stringResource(R.string.host_fingerprint,invite.host.shortFingerprint)) }
                            Text(stringResource(R.string.confirm_explanation))
                            Button(onClick=model::confirmHost,enabled=confirmReason == null,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) { Text(stringResource(R.string.confirm_action)) }
                            DisabledReason(confirmReason)
                            Text(ui.message.localized())
                        }
                    }
                }
                ui.pairing?.let { record ->
                    Text(stringResource(R.string.host_value,record.host.origin))
                    Text(stringResource(R.string.pairing_value,stringResource(ui.pairingLabel())))
                    Text(ui.message.localized())
                }
                // Recovery is the primary action for a remembered device. It
                // stays before expired-invitation diagnostics at large fonts.
                Button(onClick=model::reconnect,enabled=reconnectReason == null,modifier=Modifier.heightIn(min=48.dp)) {
                    Text(stringResource(ui.reconnectLabel()))
                }
                DisabledReason(reconnectReason)
                Button(onClick=model::status,enabled=statusReason == null,modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.refresh_status)) }
                DisabledReason(statusReason)
                ui.pairing?.let { record ->
                    if (!record.trusted && ui.pairingState in setOf("PENDING","APPROVED","BEGIN_UNCERTAIN","RECOVERY_REQUIRED")) {
                        val spokenCode = stringResource(R.string.sas_value,PairingProtocol.sas(record.requestDigest).toList().joinToString(" "))
                        SelectionContainer { Text(stringResource(R.string.sas_value,PairingProtocol.sas(record.requestDigest)),style=MaterialTheme.typography.headlineMedium,modifier=Modifier.semantics { contentDescription=spokenCode }) }
                        Text(stringResource(R.string.sas_explanation))
                    }
                }
                if (ui.pairing?.trusted != true) {
                    Button(onClick=model::readPairingStatus,enabled=pairingStatusReason == null,
                        modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.read_pairing)) }
                    DisabledReason(pairingStatusReason)
                }
                Text(stringResource(R.string.chat_unavailable))
            }
            "settings" -> {
                Text(stringResource(R.string.trust_title),style=MaterialTheme.typography.titleLarge)
                Text(ui.message.localized())
                ui.pairing?.let { SelectionContainer { Text(stringResource(R.string.saved_host_value,it.host.origin)) } }
                Button(onClick=model::revoke,enabled=statusReason == null,modifier=Modifier.heightIn(min=48.dp)) { Text(stringResource(R.string.revoke_session)) }
                DisabledReason(statusReason)
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

@Composable
private fun DisabledReason(reason: Int?) {
    if (reason != null) Text(stringResource(reason),style=MaterialTheme.typography.bodyMedium)
}
