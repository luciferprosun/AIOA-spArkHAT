package eu.sparkhat.aioa.companion

import android.os.Bundle
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
import kotlinx.serialization.json.JsonNull

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { Surface(Modifier.fillMaxSize()) { MissionScreen() } } }
    }
}

@Composable
private fun MissionScreen(model: MissionViewModel = viewModel()) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_STOP -> model.background()
                Lifecycle.Event.ON_RESUME -> model.resume()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer); onDispose { lifecycle.removeObserver(observer) }
    }
    val ui = model.ui
    var origin by remember { mutableStateOf("") }
    var tlsPin by remember { mutableStateOf("") }
    var hostKey by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var instruction by remember { mutableStateOf("Podsumuj publiczny dokument testowy.") }
    Column(Modifier.fillMaxSize().safeDrawingPadding().imePadding().verticalScroll(rememberScrollState())
        .padding(16.dp), verticalArrangement=Arrangement.spacedBy(12.dp)) {
        Text("AIOA spArkHAT",style=MaterialTheme.typography.headlineMedium)
        Text("METAGuardiansSPARK • Tasks / Mission Control")
        Text("Muse (Meta Model API) • host-side • LIVE niezweryfikowane")
        Text("Connection: ${ui.connection} • ${ui.freshness.state}")
        Text("Pairing: transport ${if(ui.enrolled) "sesja" else "brak"} • owner NOT_BOUND")
        Text("Billing Unverified • telefon nie nadaje zgody na koszt")
        Text(ui.message)
        HorizontalDivider()
        Text("Połączenie i świeży enrollment",style=MaterialTheme.typography.titleMedium)
        OutlinedTextField(origin,{ origin=it },label={ Text("Dokładny HTTPS origin Linuxa") },modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
        OutlinedTextField(tlsPin,{ tlsPin=it },label={ Text("Osobny TLS SPKI pin: sha256/…") },modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
        OutlinedTextField(hostKey,{ hostKey=it },label={ Text("Niezależny host identity SPKI (Base64 DER)") },modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
        Text("Nowy publiczny klucz urządzenia — porównaj lokalnie na hoście:")
        SelectionContainer { Text(model.publicSpki) }
        OutlinedTextField(code,{ code=it },label={ Text("Jednorazowy kod ≤5 min") },
            visualTransformation=PasswordVisualTransformation(),modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
        Button(enabled=!ui.busy && !ui.enrolled && code.isNotEmpty(),onClick={
            model.connect(origin,tlsPin,hostKey,code); code=""
        }) { Text("Sprawdź hosta i zarejestruj transport") }
        Button(enabled=ui.enrolled && !ui.busy,onClick=model::status) { Text("Podpisany status / readback") }
        Button(enabled=ui.enrolled && !ui.busy,onClick=model::revoke) { Text("Odwołaj tę sesję") }
        HorizontalDivider()
        Text("Misja • OFFLINE / LIVE",style=MaterialTheme.typography.titleMedium)
        Text("Preview jest propozycją; Run/approval wyłącznie na zaufanym hoście. LIVE zablokowane.")
        OutlinedTextField(instruction,{ if(it.toByteArray().size<=2000) instruction=it },label={ Text("Polecenie") },
            modifier=Modifier.fillMaxWidth(),enabled=!ui.busy)
        val task = ui.task
        val state = task?.let { Wire.text(it,"state") } ?: "NONE"
        Button(enabled=ui.enrolled && !ui.busy && ui.freshness.state=="FRESH" && ui.pending==null &&
            state !in setOf("PREVIEWED","RUNNING","LIVE_PENDING_AUTHORIZATION"),onClick={ model.preview(instruction) }) { Text("Preview") }
        Button(enabled=ui.enrolled && !ui.busy && ui.pending!=null,onClick=model::readback) { Text("Readback nierozliczonej propozycji") }
        if (task != null) {
            SelectionContainer { Column {
                Text("Task: ${Wire.text(task,"task_id")}")
                Text("Stan: $state • mode: ${Wire.text(task,"mode")}")
                Text("Source SHA: ${Wire.text(task,"source_sha")}")
                Text("Task digest: ${Wire.text(task,"task_digest")}")
                Text("Capsule: ${Wire.text(task,"capsule_digest")}")
                Text("Last Receipt: ${if(task["receipt"]==JsonNull) "brak / nieznany" else task["receipt"].toString()}")
            } }
        } else Text("Last Receipt: brak; brak dowodu wykonania")
        Button(enabled=ui.enrolled && !ui.busy && task!=null,onClick=model::evidence) { Text("Evidence") }
        Button(enabled=ui.enrolled && !ui.busy && ui.freshness.canStop(state),onClick=model::stop) { Text("STOP własnej misji") }
        Text("Chat: Not yet available — brak zatwierdzonego typed mobile chat.")
        Text("Transport nie oznacza owner pairing; po reinstalacji wymagany nowy enrollment.")
    }
}
