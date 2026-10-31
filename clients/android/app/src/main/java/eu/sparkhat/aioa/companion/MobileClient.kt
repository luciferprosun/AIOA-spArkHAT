package eu.sparkhat.aioa.companion

import java.security.SecureRandom
import java.util.concurrent.TimeUnit
import kotlinx.serialization.json.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody

/** Host owns model credentials and Core authority. This client has no Run port. */
class SessionUnavailable : IllegalStateException("FRESH_ENROLLMENT_REQUIRED")
data class MobileObservation(val data: JsonObject, val validUntilElapsedMs: Long)

class MobileClient(private val identity: TransportIdentity) {
    private var http: OkHttpClient? = null
    private var endpoint = ""
    private var hostSpki = ""
    private var audience = ""
    private var source = ""
    private var capsule = ""
    private var ownerScope = ""
    private var token: String? = null // memory only; never SharedPreferences/SavedState
    private var session = ""
    private var expiresAt = 0L
    private val device get() = Wire.sha(Wire.decode(identity.spki))
    val publicSpki get() = identity.spki
    private fun now() = System.currentTimeMillis()/1000
    private fun nonce(size: Int = 16): String = ByteArray(size).also { SecureRandom().nextBytes(it) }
        .joinToString("") { "%02x".format(it.toInt() and 255) }

    fun configure(origin: String, tlsPin: String, hostKey: String) {
        close(); source = ""; capsule = ""; ownerScope = ""
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
        require(!Wire.flag(caps,"run") && !Wire.flag(caps,"approve") && !Wire.flag(caps,"meta_spend"))
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
        return MobileObservation(data,Freshness.elapsedMs()+safeSeconds*1000)
    }
    private fun request(method: String, suffix: String, payload: JsonObject? = null): MobileObservation {
        val credential = token ?: throw SessionUnavailable()
        if (now() >= expiresAt) { token = null; session = ""; throw SessionUnavailable() }
        verifyHostProof() // no credential release to an unproven host
        val path = Wire.BASE+suffix; val n = nonce(); val at = now()
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
        if (data["task_id"] != null) validateMission(data)
        if (suffix == "/status" || suffix.startsWith("/status/pages/")) {
            val missions = data.getValue("missions").jsonArray
            require(missions.size <= 16 && Wire.integer(data,"total_missions") in 0L..128L)
            missions.forEach { validateMission(it.jsonObject) }
            if (data["next_cursor"] != JsonNull) require(Wire.taskId.matches(Wire.text(data,"next_cursor")))
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
    fun status() = request("GET","/status")
    fun statusPage(cursor: String): MobileObservation {
        require(Wire.taskId.matches(cursor)); return request("GET","/status/pages/$cursor")
    }
    fun preview(proposal: String, instruction: String): MobileObservation {
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
        require(Wire.taskId.matches(task)); return request("GET","/evidence/$task")
    }
    fun stop(task: String): MobileObservation {
        require(Wire.taskId.matches(task)); return request("POST","/stop",buildJsonObject { put("task_id",task) })
    }
    fun revoke() = request("POST","/session/revoke",buildJsonObject {})
    fun cancel() { http?.dispatcher?.cancelAll() }
    fun close() { cancel(); token = null; session = ""; expiresAt = 0; http?.connectionPool?.evictAll(); http = null }
}
