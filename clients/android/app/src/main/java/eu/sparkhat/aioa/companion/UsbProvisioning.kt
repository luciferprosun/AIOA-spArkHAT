package eu.sparkhat.aioa.companion

import kotlinx.serialization.json.*

data class UsbIdentity(val packageName: String, val certificate: String, val source: String, val spki: String)
data class UsbCheckpoint(val flowId: String, val digest: String, val started: Boolean)
data class UsbTransfer(val flowId: String, val digest: String, val invite: PairingInvite,
    val archived: List<String>, val archivedAgents: List<String>, val previousDevice: String) {
    companion object {
        fun parse(raw: String, identity: UsbIdentity, now: Long): UsbTransfer {
            require(raw.toByteArray(Charsets.UTF_8).size <= 16384)
            val value=Wire.parse(raw.toByteArray(Charsets.UTF_8))
            require(value.keys==setOf("schema","flow_id","device_spki","package","certificate_sha256",
                "apk_source_sha","issued_at","expires_at","trusted_host","invite","previous_device_id","archived","archived_agents"))
            require(Wire.text(value,"schema")=="aioa.mobile.usb-transfer.v1")
            require(Wire.text(value,"package")==identity.packageName && identity.packageName==UsbProvisioning.PACKAGE)
            require(Wire.hex64.matches(identity.certificate) && Wire.sha40.matches(identity.source))
            require(Wire.text(value,"certificate_sha256")==identity.certificate && Wire.text(value,"apk_source_sha")==identity.source)
            Wire.publicKey(identity.spki)
            require(Wire.text(value,"device_spki")==identity.spki)
            val flow=Wire.text(value,"flow_id"); val oldDevice=Wire.text(value,"previous_device_id")
            require(Wire.hex32.matches(flow) && Wire.hex64.matches(oldDevice))
            val at=Wire.integer(value,"issued_at"); val expires=Wire.integer(value,"expires_at")
            require(at<=now && now<expires && expires-at in 1L..300L)
            val hostValue=value.getValue("trusted_host").jsonObject
            require(hostValue.keys==setOf("origin","tls_spki_pin","host_spki","source_sha","capsule_digest","owner_scope_digest"))
            val host=TrustedHost.decode(hostValue)
            val invite=PairingProtocol.parseInvite(Wire.canonical(value.getValue("invite")).toString(Charsets.UTF_8),now)
            require(host==invite.host) { "USB_EXACT_HOST_CHANGED" }
            require(expires<=invite.expiresAt)
            fun archive(name: String): List<String> {
                val array=value.getValue(name).jsonArray
                require(array.size<=64)
                val ids=array.map { it.jsonPrimitive.also { v -> require(v.isString) }.content }
                require(ids.distinct().size==ids.size && ids.all { Wire.hex32.matches(it) })
                return ids
            }
            return UsbTransfer(flow,Wire.sha(Wire.canonical(value)),invite,archive("archived"),archive("archived_agents"),oldDevice)
        }
    }
}
data class UsbDeliverySnapshot(val payload: String?, val started: Boolean)
interface UsbDeliveryPersistence {
    fun read(): UsbDeliverySnapshot
    /** Must synchronously commit or throw before returning. */
    fun write(snapshot: UsbDeliverySnapshot)
}
/** One atomic public delivery + claim. Never a credential, private key or Core approval. */
class UsbProvisioningStore(private val persistence: UsbDeliveryPersistence) {
    fun stage(raw: String, identity: UsbIdentity, now: Long): UsbTransfer = synchronized(lock) {
        val transfer=UsbTransfer.parse(raw,identity,now)
        val previous=persistence.read()
        if (previous.payload!=null) {
            require(Wire.sha(Wire.canonical(Wire.parse(previous.payload.toByteArray())))==transfer.digest) { "USB_REPLACEMENT_DENIED" }
        } else {
            require(!previous.started) { "USB_CORRUPT_CHECKPOINT" }
            persistence.write(UsbDeliverySnapshot(raw,false))
        }
        transfer
    }
    fun claim(identity: UsbIdentity, now: Long): UsbTransfer? = synchronized(lock) {
        val snapshot=persistence.read()
        if (snapshot.started) return null // restart/ACK loss never repeat BEGIN
        val raw=snapshot.payload ?: return null
        val transfer=UsbTransfer.parse(raw,identity,now)
        check(UsbProvisioning.canClaim(transfer,UsbCheckpoint(transfer.flowId,transfer.digest,false)))
        persistence.write(snapshot.copy(started=true)) // must finish BEFORE the consumer receives the transfer
        transfer
    }
    fun publicState(): JsonObject = synchronized(lock) {
        val snapshot=persistence.read()
        val value=snapshot.payload?.let { Wire.parse(it.toByteArray()) }
        buildJsonObject {
            put("flow_id",value?.get("flow_id") ?: JsonNull)
            put("transfer_digest",value?.let { JsonPrimitive(Wire.sha(Wire.canonical(it))) } ?: JsonNull)
            put("delivery",if(value==null) "EMPTY" else if(snapshot.started) "STARTED_NO_AUTOMATIC_RETRY" else "STAGED")
        }
    }
    companion object { private val lock=Any() }
}
/** Delivery deduplication only, never approval or transport authority. */
object UsbProvisioning {
    const val PACKAGE="eu.sparkhat.aioa.companion.cosmic4"
    fun requireShell(uid: Int, debug: Boolean, variant: String, packageName: String) {
        if (uid!=2000 || !debug || variant!="cosmic4" || packageName!=PACKAGE) throw SecurityException("USB_CALLER_DENIED")
    }
    fun canClaim(transfer: UsbTransfer, previous: UsbCheckpoint): Boolean {
        require(transfer.flowId==previous.flowId && transfer.digest==previous.digest) { "USB_REPLACEMENT_DENIED" }
        return !previous.started
    }
}
