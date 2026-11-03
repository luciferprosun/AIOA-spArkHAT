package eu.sparkhat.aioa.companion

import java.security.SecureRandom
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody

/** Host owns model credentials and Core authority. This client has no Run port. */
class PairingFailure(val reason: String) : IllegalStateException(reason)
class SessionUnavailable : ExpiredTransportSession()
data class MobileObservation(val data: JsonObject, val validUntilElapsedMs: Long, val issuedAtEpochSeconds: Long)

class MobileClient(private val identity: TransportIdentity) {
    private var http: OkHttpClient? = null
    private var endpoint = ""
    private var hostSpki = ""
    private var audience = ""
    private var source = ""
    private var capsule = ""
    private var ownerScope = ""
    private var tlsPin = ""
    var capabilities: JsonObject? = null
        private set
    val deviceId get() = device
    private var token: String? = null // memory only; never SharedPreferences/SavedState
    private var session = ""
    private var expiresAt = 0L
    private val device get() = Wire.sha(Wire.decode(identity.spki))
    val publicSpki get() = identity.spki
    fun hasSession() = token != null && http != null && now() < expiresAt
    private fun now() = System.currentTimeMillis()/1000
    private fun nonce(size: Int = 16): String = ByteArray(size).also { SecureRandom().nextBytes(it) }
        .joinToString("") { "%02x".format(it.toInt() and 255) }

    fun configure(origin: String, tlsPin: String, hostKey: String) {
        close(); source = ""; capsule = ""; ownerScope = ""
        this.tlsPin = tlsPin
        endpoint = Wire.origin(origin); Wire.publicKey(hostKey)
        require(Regex("sha256/[A-Za-z0-9+/]{43}=").matches(tlsPin))
        hostSpki = hostKey; audience = Wire.sha(Wire.decode(hostKey))
        http = OkHttpClient.Builder().connectionSpecs(listOf(ConnectionSpec.Builder(ConnectionSpec.MODERN_TLS)
            .tlsVersions(TlsVersion.TLS_1_3).build()))
            .certificatePinner(CertificatePinner.Builder().add(java.net.URI(endpoint).host, tlsPin).build())
            .retryOnConnectionFailure(false).followRedirects(false).followSslRedirects(false)
            .connectTimeout(8, TimeUnit.SECONDS).readTimeout(8, TimeUnit.SECONDS)
            .callTimeout(8, TimeUnit.SECONDS).build()
    }
    private fun exchange(request: Request): JsonObject {
        val client = http ?: error("REMOTE_DEPLOYMENT_BLOCKED")
        client.newCall(request).execute().use { response ->
            if (response.code == 401) { token = null; session = ""; throw SessionUnavailable() }
            if (!response.isSuccessful) error(when(response.code) {
                403 -> "SCOPE_DENIED"; 409 -> "READBACK_REQUIRED"
                429 -> throw PairingFailure("RATE_LIMITED_STOP")
                501 -> "NOT_IMPLEMENTED"; else -> "UNKNOWN_READBACK_REQUIRED"
            })
            val stream = response.body?.byteStream() ?: error("UNKNOWN_READBACK_REQUIRED")
            // API 26 compatible bounded read; no unbounded body.string().
            val buffer = ByteArray(65537); var used = 0
            while (used < buffer.size) {
                val n = stream.read(buffer,used,buffer.size-used)
                if (n < 0) break
                used += n
            }
            require(used <= 65536)
            return Wire.parse(buffer.copyOf(used))
        }
    }
    fun verifyHostProof(): JsonObject {
        val challenge = nonce(32)
        val response = exchange(Request.Builder().url(endpoint+Wire.BASE+"/capabilities")
            .header("X-AIOA-Challenge", challenge).get().build())
        val proof = response.getValue("proof").jsonObject
        val caps = response.getValue("capabilities").jsonObject
        Wire.verify(hostSpki, Wire.text(response,"signature"), proof); Wire.fresh(proof, now())
        require(Wire.text(proof,"schema") == Wire.HOST && Wire.text(proof,"challenge") == challenge &&
            Wire.text(proof,"origin") == endpoint && Wire.text(proof,"audience") == audience &&
            Wire.text(proof,"host_spki") == hostSpki && Wire.text(proof,"capabilities_sha256") == Wire.sha(Wire.canonical(caps)))
        val newSource = Wire.text(proof,"source_sha"); val newCapsule = Wire.text(proof,"capsule_digest")
        val newScope = Wire.text(proof,"owner_scope_digest")
        if (token != null) require(newSource == source && newCapsule == capsule && newScope == ownerScope)
        source = newSource; capsule = newCapsule; ownerScope = newScope
        require(Wire.sha40.matches(source) && Wire.hex64.matches(capsule) && Wire.hex64.matches(ownerScope))
        // Test identities must never become production phone pairing.
        require(Wire.text(caps,"profile") != "OFFLINE_FIXTURE" &&
            Wire.text(caps,"remote_deployment") == "TLS_HOST_VERIFIED") { "REMOTE_DEPLOYMENT_BLOCKED" }
        require(listOf("run","approve","meta_spend","native_execute","install","github_write").all { !Wire.flag(caps,it) })
        capabilities = caps
        return caps
    }
    fun enroll(code: String): MobileObservation {
        token = null; session = ""
        verifyHostProof() // before code, token or device proof is sent
        require(Regex("[0-9a-f]{48}").matches(code))
        val n = nonce(); val path = Wire.BASE+"/enrollment/redeem"
        val proof = buildJsonObject {
            put("schema",Wire.ENROLL); put("code_sha256",Wire.sha(code.toByteArray(Charsets.US_ASCII)))
            put("device_spki",identity.spki); put("nonce",n); put("issued_at",now()); put("audience",audience)
            put("source_sha",source); put("capsule_digest",capsule)
        }
        val body = buildJsonObject {
            proof.forEach { (k,v) -> if (k != "schema" && k != "code_sha256") put(k,v) }
            put("code",code); put("signature",identity.sign(proof))
        }
        val response = exchange(Request.Builder().url(endpoint+path)
            .post(Wire.canonical(body).toRequestBody("application/json".toMediaType())).build())
        val data = response.getValue("data").jsonObject
        val newSession = Wire.text(data,"session_id")
        require(Wire.hex32.matches(newSession))
        val observation = verifyObservation(response,n,"POST",path,newSession)
        val newToken = Wire.text(data,"token")
        require(Regex("[A-Za-z0-9_-]{43}").matches(newToken) && Wire.text(data,"device_id") == device &&
            Wire.integer(data,"expires_at") in (now()+1)..(now()+630) && Wire.text(data,"owner_authority") == "NOT_BOUND")
        token = newToken; session = newSession; expiresAt = Wire.integer(data,"expires_at")
        return observation
    }
    private fun verifyObservation(response: JsonObject, n: String, method: String, path: String, expectedSession: String = session): MobileObservation {
        val proof = response.getValue("proof").jsonObject
        val data = response.getValue("data").jsonObject
        Wire.verify(hostSpki,Wire.text(response,"signature"),proof); Wire.fresh(proof,now())
        require(Wire.text(proof,"schema") == Wire.OBSERVATION && Wire.text(proof,"audience") == audience &&
            Wire.text(proof,"nonce") == n && Wire.text(proof,"method") == method && Wire.text(proof,"path") == path &&
            Wire.text(proof,"device_id") == device && Wire.text(proof,"session_id") == expectedSession &&
            Wire.text(proof,"source_sha") == source && Wire.text(proof,"capsule_digest") == capsule &&
            Wire.text(proof,"owner_scope_digest") == ownerScope &&
            Wire.text(proof,"data_sha256") == Wire.sha(Wire.canonical(data)))
        val sessionRemaining = if (expiresAt > now()) expiresAt-now() else 30L
        val safeSeconds = (minOf(30L,Wire.integer(proof,"expires_at")-now(),sessionRemaining)-1).coerceAtLeast(0)
        return MobileObservation(data,Freshness.elapsedMs()+safeSeconds*1000,Wire.integer(proof,"issued_at"))
    }
    private fun request(method: String, suffix: String, payload: JsonObject? = null, apiBase: String = Wire.BASE): MobileObservation {
        require(apiBase in setOf(Wire.BASE,Wire.VIEW_BASE))
        if (apiBase == Wire.VIEW_BASE) check(capabilities?.get("profile")?.jsonPrimitive?.content == "OFFLINE_FIXTURE") { "CAPABILITY_UNAVAILABLE" }
        val credential = token ?: throw SessionUnavailable()
        if (now() >= expiresAt) { token = null; session = ""; throw SessionUnavailable() }
        verifyHostProof() // no credential release to an unproven host
        val path = apiBase+suffix; val n = nonce(); val at = now()
        val body = payload?.let { Wire.canonical(it) } ?: byteArrayOf()
        require(body.size <= 16384)
        val proof = buildJsonObject {
            put("schema",Wire.REQUEST); put("method",method); put("path",path); put("body_sha256",Wire.sha(body))
            put("token_sha256",Wire.sha(credential.toByteArray(Charsets.US_ASCII))); put("nonce",n); put("issued_at",at)
            put("audience",audience); put("source_sha",source); put("capsule_digest",capsule)
        }
        val builder = Request.Builder().url(endpoint+path).header("Authorization","Bearer $credential")
            .header("X-AIOA-Nonce",n).header("X-AIOA-Issued-At",at.toString()).header("X-AIOA-Audience",audience)
            .header("X-AIOA-Source-SHA",source).header("X-AIOA-Capsule",capsule)
            .header("X-AIOA-Signature",identity.sign(proof))
        if (method == "GET") builder.get() else builder.post(body.toRequestBody("application/json".toMediaType()))
        val observation = verifyObservation(exchange(builder.build()),n,method,path)
        val data = observation.data
        if (data["task_id"] != null) {
            if (apiBase == Wire.VIEW_BASE) AgentMissionView.decode(data,source,capsule,ownerScope) else validateMission(data)
        }
        if (apiBase == Wire.BASE && (suffix == "/status" || suffix.startsWith("/status/pages/"))) {
            val missions = data.getValue("missions").jsonArray
            require(missions.size <= 16 && Wire.integer(data,"total_missions") in 0L..128L)
            missions.forEach { validateMission(it.jsonObject) }
            if (data["next_cursor"] != JsonNull) require(Wire.taskId.matches(Wire.text(data,"next_cursor")))
        }
        if (apiBase == Wire.VIEW_BASE && (suffix == "/status" || suffix.startsWith("/status/pages/"))) {
            require(Wire.text(data,"schema") == "aioa.mobile.agent-status.v2" &&
                Wire.text(data,"owner_authority") == "NOT_BOUND" && !Wire.flag(data,"live_verified"))
            val missions = data.getValue("missions").jsonArray
            require(missions.size <= 16 && Wire.integer(data,"total_missions") in 0L..128L)
            missions.forEach { item ->
                val value = item.jsonObject
                require(AgentMissionView.taskPattern.matches(Wire.text(value,"task_id")) &&
                    Wire.text(value,"source_sha") == source && Wire.text(value,"capsule_digest") == capsule &&
                    Wire.text(value,"mode") == "OFFLINE_FIXTURE")
                AgentState.valueOf(Wire.text(value,"state"))
            }
            if (data["next_cursor"] != JsonNull) require(AgentMissionView.taskPattern.matches(Wire.text(data,"next_cursor")))
        }
        if (apiBase == Wire.VIEW_BASE && suffix == "/providers") {
            require(Wire.text(data,"schema") == "aioa.provider-catalog.v1" && !Wire.flag(data,"automatic_fallback"))
            val providers = data.getValue("providers").jsonArray
            require(providers.size <= 8)
            providers.forEach { require(!Wire.flag(it.jsonObject,"live_enabled")) }
        }
        if (suffix == "/session/revoke") { token = null; session = "" }
        return observation
    }
    private fun validateMission(data: JsonObject) {
        require(Wire.taskId.matches(Wire.text(data,"task_id")) && Wire.hex64.matches(Wire.text(data,"task_digest")) &&
            Wire.text(data,"source_sha") == source && Wire.text(data,"capsule_digest") == capsule &&
            Wire.text(data,"owner_scope_digest") == ownerScope && !Wire.flag(data,"verified") &&
            !Wire.flag(data,"live_verified") && !Wire.flag(data,"can_run") &&
            Wire.text(data,"model_id") == "muse-spark-1.3" && Wire.text(data,"provider_id") == "meta_model_api" &&
            Wire.text(data,"mode") == "OFFLINE_FIXTURE")
        require(Wire.text(data,"state") in setOf("PREVIEWED","RUNNING","OFFLINE_FIXTURE","UNKNOWN","DENIED","STOPPED","BLOCKED"))
        if (data["receipt"] != JsonNull) {
            val receipt = data.getValue("receipt").jsonObject
            require(Wire.text(receipt,"kind") == "OFFLINE_FIXTURE" && !Wire.flag(receipt,"verified") &&
                Wire.hex64.matches(Wire.text(receipt,"content_sha256")))
        }
    }
    private fun currentHost() = TrustedHost(endpoint,tlsPin,hostSpki,source,capsule,ownerScope)
    /** Clear old bearer first. Only the pinned public binding may admit fresh source/capsule. */
    fun preparePairing(bound: TrustedHost): TrustedHost {
        configure(bound.origin,bound.tlsPin,bound.spki)
        verifyHostProof()
        return currentHost().also { bound.requireSameBinding(it) }
    }
    fun pairingRequest(suffix: String, fields: JsonObject): JsonObject {
        require(suffix in setOf("/pairing/begin","/pairing/status","/pairing/complete","/session/challenge","/session/reconnect"))
        val unsigned = buildJsonObject {
            put("schema","aioa.mobile.pairing-request.v1"); put("device_spki",identity.spki)
            put("nonce",nonce()); put("issued_at",now()); put("audience",audience); put("origin",endpoint)
            put("source_sha",source); put("capsule_digest",capsule)
            fields.forEach { (key,value) -> put(key,value) }
        }
        val proof = JsonObject(unsigned + mapOf("method" to JsonPrimitive("POST"),"path" to JsonPrimitive(Wire.BASE+suffix)))
        return JsonObject(unsigned + ("signature" to JsonPrimitive(identity.sign(proof))))
    }
    fun beginDigest(request: JsonObject) = Wire.sha(Wire.canonical(JsonObject(request.filterKeys { it != "signature" } +
        mapOf("method" to JsonPrimitive("POST"),"path" to JsonPrimitive(Wire.BASE+"/pairing/begin")))))
    fun pairingExchange(suffix: String, body: JsonObject): JsonObject {
        val raw = Wire.canonical(body); require(raw.size <= 16384)
        val response = exchange(Request.Builder().url(endpoint+Wire.BASE+suffix)
            .post(raw.toRequestBody("application/json".toMediaType())).build())
        return PairingProtocol.verifyResponse(response,body,suffix,currentHost(),now())
    }
    fun pairingStatus(record: PairingRecord): JsonObject {
        val response = pairingExchange("/pairing/status",pairingRequest("/pairing/status",buildJsonObject { put("request_id",record.requestId) }))
        PairingProtocol.validateStatus(response,record,device)
        return response
    }
    fun completePairing(record: PairingRecord) {
        val data = pairingExchange("/pairing/complete",pairingRequest("/pairing/complete",buildJsonObject { put("request_id",record.requestId) }))
        acceptPairingSession(data)
    }
    fun reconnectSession() {
        val challenge = pairingExchange("/session/challenge",pairingRequest("/session/challenge",buildJsonObject { put("device_id",device) }))
        PairingProtocol.validateChallenge(challenge,device,now())
        val data = pairingExchange("/session/reconnect",pairingRequest("/session/reconnect",buildJsonObject {
            put("device_id",device); put("challenge_id",Wire.text(challenge,"challenge_id")); put("challenge_nonce",Wire.text(challenge,"challenge_nonce"))
        }))
        acceptPairingSession(data)
    }
    private fun acceptPairingSession(data: JsonObject) {
        require(data.keys == setOf("token","session_id","device_id","expires_at","owner_authority"))
        val newToken = Wire.text(data,"token"); val newSession = Wire.text(data,"session_id")
        val expiry = Wire.integer(data,"expires_at")
        require(Regex("[A-Za-z0-9_-]{43}").matches(newToken) && Wire.hex32.matches(newSession) &&
            Wire.text(data,"device_id") == device && expiry in (now()+1)..(now()+600) && Wire.text(data,"owner_authority") == "NOT_BOUND")
        token = newToken; session = newSession; expiresAt = expiry
    }
    fun supports(name: String) = capabilities?.let { it[name]?.jsonPrimitive?.booleanOrNull == true } ?: false
    fun status() = request("GET","/status")
    fun statusPage(cursor: String): MobileObservation {
        require(Wire.taskId.matches(cursor)); return request("GET","/status/pages/$cursor")
    }
    fun preview(proposal: String, instruction: String): MobileObservation {
        check(supports("preview")) { "CAPABILITY_UNAVAILABLE" }
        require(Wire.hex32.matches(proposal) && instruction.toByteArray().size in 1..2000)
        return request("POST","/preview",buildJsonObject {
            put("proposal_id",proposal); put("instruction",instruction); put("mode","OFFLINE_FIXTURE")
            put("target_url","https://docs.example.org/offline-fixture")
        })
    }
    fun readback(proposal: String): MobileObservation {
        require(Wire.hex32.matches(proposal)); return request("GET","/proposals/$proposal")
    }
    fun evidence(task: String): MobileObservation {
        check(supports("evidence")) { "CAPABILITY_UNAVAILABLE" }
        require(Wire.taskId.matches(task)); return request("GET","/evidence/$task")
    }
    fun stop(task: String): MobileObservation {
        check(supports("stop")) { "CAPABILITY_UNAVAILABLE" }
        require(Wire.taskId.matches(task)); return request("POST","/stop",buildJsonObject { put("task_id",task) })
    }
    fun revoke() = request("POST","/session/revoke",buildJsonObject {})
    fun agentStatus() = request("GET","/status",apiBase=Wire.VIEW_BASE)
    fun agentEvidence(task: String): MobileObservation {
        require(AgentMissionView.taskPattern.matches(task)); return request("GET","/tasks/$task",apiBase=Wire.VIEW_BASE)
    }
    fun agentProposal(proposal: String, sourceTask: String? = null): MobileObservation {
        require(Wire.hex32.matches(proposal))
        if (sourceTask != null) require(AgentMissionView.taskPattern.matches(sourceTask))
        return request("POST","/propose",buildJsonObject {
            put("schema","aioa.agent-proposal.v2"); put("request_id",proposal); put("provider_id","meta_model_api")
            put("recipe_id",if(sourceTask == null) "sensorbridge-v1" else "git-commit-v1")
            if (sourceTask != null) put("source_task_id",sourceTask)
        },apiBase=Wire.VIEW_BASE)
    }
    fun agentReadback(proposal: String): MobileObservation {
        require(Wire.hex32.matches(proposal)); return request("GET","/proposals/$proposal",apiBase=Wire.VIEW_BASE)
    }
    fun agentStop(task: String): MobileObservation {
        require(AgentMissionView.taskPattern.matches(task))
        return request("POST","/stop",buildJsonObject { put("task_id",task) },apiBase=Wire.VIEW_BASE)
    }
    fun agentProviders() = request("GET","/providers",apiBase=Wire.VIEW_BASE)
    fun cancel() { http?.dispatcher?.cancelAll() }
    fun close() { capabilities = null; cancel(); token = null; session = ""; expiresAt = 0; http?.connectionPool?.evictAll(); http = null }
}
