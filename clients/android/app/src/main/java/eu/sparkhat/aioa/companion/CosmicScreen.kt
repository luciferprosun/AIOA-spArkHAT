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
    LaunchedEffect(incomingPacket) {
        incomingPacket?.let { model.importPacket(it); consumed() }
    }
    var page by rememberSaveable { mutableStateOf("Home") }
    MaterialTheme(colorScheme=CosmicColors) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize().safeDrawingPadding().imePadding()) {
                // Two rows avoid clipped four-way navigation at accessibility font scales.
                listOf(listOf("Home","Missions"),listOf("Repositories","Settings")).forEach { row ->
                    Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(8.dp)) {
                        row.forEach { title ->
                            OutlinedButton(onClick={ page=title },modifier=Modifier.weight(1f).heightIn(min=48.dp)) {
                                Text(if(page == title) "$title • selected" else title)
                            }
                        }
                    }
                }
                Box(Modifier.weight(1f)) {
                    if (page == "Missions" || page == "Advanced enrollment") LegacyMissionScreen(model,showConnection=page == "Advanced enrollment")
                    else CosmicPage(page,model) { page="Advanced enrollment" }
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
    if (forget) AlertDialog(onDismissRequest={ forget=false },title={ Text("Forget this host on this phone?") },
        text={ Text("Linux approval remains active until you revoke the device on Linux. Existing unresolved mission IDs stay retained.") },
        confirmButton={ TextButton(onClick={ model.forgetHost(); forget=false }) { Text("Forget local binding") } },
        dismissButton={ TextButton(onClick={ forget=false }) { Text("Cancel") } })
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),verticalArrangement=Arrangement.spacedBy(16.dp)) {
        Text("AIOA",style=MaterialTheme.typography.headlineLarge,modifier=Modifier.semantics { heading() })
        Text(page,style=MaterialTheme.typography.titleLarge)
        when(page) {
            "Home" -> {
                Text("Your Linux host. Your decisions.",style=MaterialTheme.typography.headlineSmall)
                Text("Connection: ${ui.connection}")
                Text(ui.message)
                Button(enabled=!ui.busy,onClick={
                    try {
                        val options = GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build()
                        GmsBarcodeScanning.getClient(context,options).startScan()
                            .addOnSuccessListener { barcode ->
                                val raw = barcode.rawValue
                                if (raw == null) model.scannerMessage("QR has no text packet. Use a fresh Linux QR.") else model.importPacket(raw)
                            }
                            .addOnCanceledListener { model.scannerMessage("Scan cancelled. You can scan again or paste the signed packet.") }
                            .addOnFailureListener { model.scannerMessage("Scanner unavailable. Google Play services may need the scanner module on first use. Paste the signed packet below, or retry after the module is available."); manual=true }
                    } catch (_: Exception) { manual=true; model.scannerMessage("Scanner unavailable. Paste the signed packet from your trusted Linux display.") }
                },modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) { Text("Connect my AIOA") }
                Text("Scan the QR shown by your trusted Linux AIOA. No camera permission is required by this app. First use may download the Google Play services scanner module.")
                TextButton(onClick={ manual=!manual },enabled=!ui.busy,modifier=Modifier.heightIn(min=48.dp)) { Text("Paste a signed pairing packet") }
                if (manual) {
                    OutlinedTextField(packet,{ if(it.length<=22000) packet=it },label={ Text("Signed JSON or aioa://pair link") },modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
                    Button(onClick={ model.importPacket(packet); packet="" },enabled=!ui.busy && packet.isNotBlank(),modifier=Modifier.heightIn(min=48.dp)) { Text("Read packet") }
                }
                ui.invite?.let { invite ->
                    Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(16.dp),verticalArrangement=Arrangement.spacedBy(12.dp)) {
                            Text("Confirm your host",style=MaterialTheme.typography.titleLarge)
                            SelectionContainer { Text(invite.host.origin) }
                            Text("Only continue if this packet came from your own trusted Linux display. The signature proves packet integrity; it does not identify an unknown computer for you.")
                            Button(onClick=model::confirmHost,enabled=!ui.busy,modifier=Modifier.fillMaxWidth().heightIn(min=48.dp)) { Text("This is my AIOA — connect") }
                        }
                    }
                }
                ui.pairing?.let { record ->
                    Text("Host: ${record.host.origin}")
                    Text("Pairing: ${ui.pairingState}")
                    if (ui.pairingState in setOf("PENDING","APPROVED","BEGIN_UNCERTAIN","RECOVERY_REQUIRED")) {
                        SelectionContainer { Text("Comparison code: ${PairingProtocol.sas(record.requestDigest)}",style=MaterialTheme.typography.headlineMedium,modifier=Modifier.semantics { contentDescription="Comparison code: "+PairingProtocol.sas(record.requestDigest).toList().joinToString(" ") }) }
                        Text("Compare all six digits on Linux. Approve only the exact matching request there.")
                    }
                    Button(onClick=model::readPairingStatus,enabled=!ui.busy && !ui.enrolled && System.currentTimeMillis()/1000 < record.expiresAt,
                        modifier=Modifier.heightIn(min=48.dp)) { Text("Read pairing status") }
                    Button(onClick=model::reconnect,enabled=!ui.busy && (record.trusted || record.completeAttempted),modifier=Modifier.heightIn(min=48.dp)) {
                        Text(if(ui.pairingState == "CONNECTED") "Refresh connection" else "Reconnect / recover session")
                    }
                }
                Button(onClick=model::status,enabled=ui.enrolled && !ui.busy,modifier=Modifier.heightIn(min=48.dp)) { Text("Refresh signed status") }
                Text("Owner approval stays on Linux. Chat: Not yet available in this host profile.")
            }
            "Repositories" -> {
                Text("Repository controls are unavailable in this host profile.")
                Text("The phone has no repository execution, installation, push or approval authority. View existing signed mission evidence in Missions when the host supports it.")
            }
            "Settings" -> {
                Text("Connection and trust",style=MaterialTheme.typography.titleLarge)
                Text(ui.message)
                ui.pairing?.let { SelectionContainer { Text("Saved host: ${it.host.origin}") } }
                Button(onClick=model::revoke,enabled=ui.enrolled && !ui.busy,modifier=Modifier.heightIn(min=48.dp)) { Text("Revoke current session") }
                Text("This ends the current session. To block future reconnects, revoke the device on Linux.")
                OutlinedButton(onClick={ forget=true },enabled=!ui.busy,modifier=Modifier.heightIn(min=48.dp)) { Text("Forget local host binding") }
                Text("Reduced motion: this interface uses static screens. Text follows system size and all content scrolls.")
                TextButton(onClick={ diagnostics=!diagnostics },modifier=Modifier.heightIn(min=48.dp)) { Text("Diagnostic details") }
                if (diagnostics) TextButton(onClick=advanced,modifier=Modifier.heightIn(min=48.dp)) { Text("Advanced legacy enrollment") }
                if (diagnostics) SelectionContainer {
                    Column(verticalArrangement=Arrangement.spacedBy(12.dp)) {
                        Text("Device public identity: ${model.publicSpki}")
                        ui.pairing?.let {
                            Text("Host identity: ${it.host.spki}\nTLS pin: ${it.host.tlsPin}\nOwner scope: ${it.host.ownerScope}\nSource: ${it.host.source}\nCapsule: ${it.host.capsule}\nRequest: ${it.requestId}\nDigest: ${it.requestDigest}")
                        }
                        Text("Capabilities: ${ui.capabilities ?: "No verified host proof in this session"}")
                        Text("Bearer remains in memory; backups are disabled. Package: eu.sparkhat.aioa.companion")
                    }
                }
            }
        }
    }
}
