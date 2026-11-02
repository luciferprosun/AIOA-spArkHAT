package eu.sparkhat.aioa.companion

import java.net.URI
import java.util.Base64
import kotlinx.serialization.json.*

data class TrustedHost(val origin: String, val tlsPin: String, val spki: String,
    val source: String, val capsule: String, val ownerScope: String) {
    val audience get() = Wire.sha(Wire.decode(spki))
    fun requireSameBinding(other: TrustedHost) {
        require(origin == other.origin && tlsPin == other.tlsPin && spki == other.spki && ownerScope == other.ownerScope) {
            "HOST_BINDING_CHANGED"
        }
    }
    fun json() = buildJsonObject {
        put("origin",origin); put("tls_spki_pin",tlsPin); put("host_spki",spki)
        put("source_sha",source); put("capsule_digest",capsule); put("owner_scope_digest",ownerScope)
    }
    companion object {
        fun decode(value: JsonObject): TrustedHost {
            val host = TrustedHost(Wire.origin(Wire.text(value,"origin")),Wire.text(value,"tls_spki_pin"),
                Wire.text(value,"host_spki"),Wire.text(value,"source_sha"),Wire.text(value,"capsule_digest"),Wire.text(value,"owner_scope_digest"))
            Wire.publicKey(host.spki)
            require(Regex("sha256/[A-Za-z0-9+/]{43}=").matches(host.tlsPin))
            require(Wire.decode(host.tlsPin.removePrefix("sha256/")).size == 32)
            require(Wire.sha40.matches(host.source) && Wire.hex64.matches(host.capsule) && Wire.hex64.matches(host.ownerScope))
            return host
        }
    }
}
data class PairingInvite(val envelope: JsonObject, val host: TrustedHost, val expiresAt: Long)

/** Public metadata only; one atomic preferences value survives lost begin/complete ACKs. */
data class PairingRecord(val host: TrustedHost, val requestId: String, val requestDigest: String,
    val expiresAt: Long, val completeAttempted: Boolean, val trusted: Boolean) {
    fun encode() = Wire.canonical(buildJsonObject {
        put("host",host.json()); put("request_id",requestId); put("request_digest",requestDigest)
        put("expires_at",expiresAt); put("complete_attempted",completeAttempted); put("trusted",trusted)
    }).toString(Charsets.UTF_8)
    companion object {
        fun decode(raw: String): PairingRecord {
            val value = Wire.parse(raw.toByteArray(Charsets.UTF_8))
            require(value.keys == setOf("host","request_id","request_digest","expires_at","complete_attempted","trusted"))
            val id = Wire.text(value,"request_id"); val digest = Wire.text(value,"request_digest")
            require(Wire.hex32.matches(id) && Wire.hex64.matches(digest))
            return PairingRecord(TrustedHost.decode(value.getValue("host").jsonObject),id,digest,
                Wire.integer(value,"expires_at"),PairingProtocol.boolean(value,"complete_attempted"),PairingProtocol.boolean(value,"trusted"))
        }
    }
}
object PairingProtocol {
    fun boolean(obj: JsonObject, field: String): Boolean {
        val value = obj.getValue(field).jsonPrimitive
        require(!value.isString && value.content in setOf("true","false"))
        return value.boolean
    }
    fun parseInvite(input: String, now: Long): PairingInvite {
        require(input.length <= 22000)
        val raw = if (input.startsWith("aioa:")) {
            val uri = URI(input)
            require(uri.scheme == "aioa" && uri.rawAuthority == "pair" && uri.rawPath.isNullOrEmpty() && uri.rawQuery == null)
            val fragment = uri.rawFragment ?: error("MISSING_PACKET")
            require(Regex("[A-Za-z0-9_-]+").matches(fragment))
            Base64.getUrlDecoder().decode(fragment).also {
                require(Base64.getUrlEncoder().withoutPadding().encodeToString(it) == fragment)
            }
        } else input.toByteArray(Charsets.UTF_8)
        require(raw.size <= 16384)
        val packet = Wire.parse(raw)
        require(packet.keys == setOf("invite","signature"))
        val invite = packet.getValue("invite").jsonObject
        require(invite.keys == setOf("schema","invite_id","origin","host_spki","audience","tls_spki_pin",
            "source_sha","capsule_digest","owner_scope_digest","issued_at","expires_at"))
        require(Wire.text(invite,"schema") == "aioa.mobile.pairing-invite.v1" && Wire.hex32.matches(Wire.text(invite,"invite_id")))
        val host = TrustedHost.decode(invite)
        require(Wire.text(invite,"audience") == host.audience)
        Wire.verify(host.spki,Wire.text(packet,"signature"),invite)
        val at = Wire.integer(invite,"issued_at"); val expires = Wire.integer(invite,"expires_at")
        require(at <= now && now < expires && expires-at in 1L..300L) { "INVITE_EXPIRED_OR_CLOCK_INVALID" }
        return PairingInvite(packet,host,expires)
    }
    fun sas(digest: String): String {
        require(Wire.hex64.matches(digest))
        return (digest.take(8).toLong(16)%1000000).toString().padStart(6,'0')
    }
    fun canComplete(state: String, alreadyAttempted: Boolean) = state == "APPROVED" && !alreadyAttempted
    fun verifyResponse(response: JsonObject, request: JsonObject, suffix: String, host: TrustedHost, now: Long): JsonObject {
        require(response.keys == setOf("ok","data","proof","signature") && boolean(response,"ok"))
        val proof = response.getValue("proof").jsonObject
        require(proof.keys == setOf("schema","method","path","request_sha256","nonce","audience","origin",
            "source_sha","capsule_digest","owner_scope_digest","issued_at","expires_at","data_sha256"))
        val data = response.getValue("data").jsonObject
        Wire.verify(host.spki,Wire.text(response,"signature"),proof); Wire.fresh(proof,now)
        require(Wire.text(proof,"schema") == "aioa.mobile.pairing-response.v1" && Wire.text(proof,"method") == "POST" &&
            Wire.text(proof,"path") == Wire.BASE+suffix && Wire.text(proof,"request_sha256") == Wire.sha(Wire.canonical(request)) &&
            Wire.text(proof,"nonce") == Wire.text(request,"nonce") && Wire.text(proof,"audience") == host.audience &&
            Wire.text(proof,"origin") == host.origin && Wire.text(proof,"source_sha") == host.source &&
            Wire.text(proof,"capsule_digest") == host.capsule && Wire.text(proof,"owner_scope_digest") == host.ownerScope &&
            Wire.text(proof,"data_sha256") == Wire.sha(Wire.canonical(data))) { "SIGNED_RESPONSE_MISMATCH" }
        return data
    }
    fun validateChallenge(challenge: JsonObject, device: String, now: Long) {
        require(challenge.keys == setOf("device_id","challenge_id","challenge_nonce","expires_at"))
        require(Wire.text(challenge,"device_id") == device && Wire.hex32.matches(Wire.text(challenge,"challenge_id")) &&
            Wire.hex32.matches(Wire.text(challenge,"challenge_nonce")) && Wire.integer(challenge,"expires_at") in (now+1)..(now+60))
    }
    fun validateStatus(data: JsonObject, record: PairingRecord, device: String): String {
        require(data.keys == setOf("request_id","request_digest","device_id","device_name","sas","state","expires_at","automatic_retry"))
        require(Wire.text(data,"request_id") == record.requestId && Wire.text(data,"request_digest") == record.requestDigest &&
            Wire.text(data,"device_id") == device && Wire.text(data,"sas") == sas(record.requestDigest) &&
            Wire.integer(data,"expires_at") == record.expiresAt && !boolean(data,"automatic_retry"))
        val name = Wire.text(data,"device_name")
        require(name.length in 1..64 && name.all { it.code in 32..126 })
        val state = Wire.text(data,"state")
        require(state in setOf("PENDING","APPROVED","COMPLETED","EXPIRED","REVOKED"))
        return state
    }
}
