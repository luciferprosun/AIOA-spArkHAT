package eu.sparkhat.aioa.companion

import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Synthetic transport contracts only; never owner authority or a LIVE receipt. */
class UsbProvisioningTest {
    private val key = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
    private val spki = Wire.b64(key.public.encoded)
    private val identity get() = UsbIdentity("eu.sparkhat.aioa.companion.cosmic4","a".repeat(64),"b".repeat(40),spki)
    private fun payload(): JsonObject {
        val host = TrustedHost("https://fixture.invalid","sha256/"+Wire.b64(ByteArray(32)),spki,"c".repeat(40),"d".repeat(64),"e".repeat(64))
        val invite = buildJsonObject {
            host.json().forEach { (k,v) -> put(k,v) }; put("schema","aioa.mobile.pairing-invite.v1")
            put("audience",host.audience); put("invite_id","f".repeat(32)); put("issued_at",1000); put("expires_at",1300)
        }
        val signature = Wire.b64(Signature.getInstance("SHA256withECDSA").run {
            initSign(key.private); update(Wire.canonical(invite)); sign()
        })
        return buildJsonObject {
            put("schema","aioa.mobile.usb-transfer.v1"); put("flow_id","1".repeat(32))
            put("device_spki",spki); put("package",identity.packageName); put("certificate_sha256",identity.certificate)
            put("apk_source_sha",identity.source); put("issued_at",1000); put("expires_at",1300)
            put("trusted_host",host.json()); put("previous_device_id","2".repeat(64))
            put("invite",buildJsonObject { put("invite",invite); put("signature",signature) })
            put("archived",JsonArray(listOf(JsonPrimitive("3".repeat(32))))); put("archived_agents",JsonArray(emptyList()))
        }
    }
    private fun raw(p: JsonObject = payload()) = Wire.canonical(p).toString(Charsets.UTF_8)
    @Test fun exactSignedPublicTransferIsAcceptedAndOldSourceIsNotNewAuthority() {
        val transfer=UsbTransfer.parse(raw(),identity,1001)
        assertEquals("1".repeat(32),transfer.flowId)
        assertEquals(listOf("3".repeat(32)),transfer.archived)
        assertEquals("c".repeat(40),transfer.invite.host.source)
        assertNotEquals(identity.source,transfer.invite.host.source) // separate app/Core source
    }
    @Test fun rejectsWrongDevicePackageSignerApkSourceAndClock() {
        for ((field,value) in listOf("device_spki" to Wire.b64(KeyPairGenerator.getInstance("EC").apply { initialize(256) }.generateKeyPair().public.encoded),
            "package" to "other.app", "certificate_sha256" to "0".repeat(64),"apk_source_sha" to "0".repeat(40))) {
            val bad=JsonObject(payload()+(field to JsonPrimitive(value)))
            assertThrows(Exception::class.java) { UsbTransfer.parse(raw(bad),identity,1001) }
        }
        for (time in listOf(999L,1300L)) assertThrows(Exception::class.java) { UsbTransfer.parse(raw(),identity,time) }
    }
    @Test fun rejectsUntrustedHostForgedInviteUnknownFieldsAndOversize() {
        val original=payload(); val host=original.getValue("trusted_host").jsonObject
        val wrongHost=JsonObject(host+("owner_scope_digest" to JsonPrimitive("0".repeat(64))))
        assertThrows(Exception::class.java) { UsbTransfer.parse(raw(JsonObject(original+("trusted_host" to wrongHost))),identity,1001) }
        val wrongInvite=JsonObject(original.getValue("invite").jsonObject+("signature" to JsonPrimitive("AAAA")))
        assertThrows(Exception::class.java) { UsbTransfer.parse(raw(JsonObject(original+("invite" to wrongInvite))),identity,1001) }
        for (field in listOf("token","owner_approved","session","enrollment_code")) {
            assertThrows(Exception::class.java) { UsbTransfer.parse(raw(JsonObject(original+(field to JsonPrimitive("forged")))),identity,1001) }
        }
        assertThrows(Exception::class.java) { UsbTransfer.parse("x".repeat(16385),identity,1001) }
    }
    @Test fun nestedHostCannotSmuggleCredentialsOrChangeExactSource() {
        val original=payload(); val host=original.getValue("trusted_host").jsonObject
        for ((field,value) in listOf("token" to "private", "session" to "private", "enrollment_code" to "private",
            "source_sha" to "0".repeat(40),"capsule_digest" to "0".repeat(64))) {
            val changed=JsonObject(host+(field to JsonPrimitive(value)))
            assertThrows(Exception::class.java) { UsbTransfer.parse(raw(JsonObject(original+("trusted_host" to changed))),identity,1001) }
        }
    }
    @Test fun duplicateOrRestartNeverClaimsAnotherBeginAndChangedPayloadCannotReplaceIt() {
        val transfer=UsbTransfer.parse(raw(),identity,1001)
        val staged=UsbCheckpoint(transfer.flowId,transfer.digest,false)
        assertTrue(UsbProvisioning.canClaim(transfer,staged))
        val started=staged.copy(started=true)
        assertFalse(UsbProvisioning.canClaim(transfer,started))
        val other=transfer.copy(flowId="9".repeat(32))
        assertThrows(Exception::class.java) { UsbProvisioning.canClaim(other,started) }
        assertThrows(Exception::class.java) { UsbProvisioning.canClaim(transfer.copy(digest="9".repeat(64)),staged) }
    }
    @Test fun onlyRealShellUidInExactDebugVariantMayUseUsb() {
        UsbProvisioning.requireShell(2000,true,"cosmic4",identity.packageName)
        for (uid in listOf(0,1000,10000,102000,2001)) assertThrows(SecurityException::class.java) {
            UsbProvisioning.requireShell(uid,true,"cosmic4",identity.packageName)
        }
        assertThrows(SecurityException::class.java) { UsbProvisioning.requireShell(2000,false,"cosmic4",identity.packageName) }
        assertThrows(SecurityException::class.java) { UsbProvisioning.requireShell(2000,true,"debug",identity.packageName) }
        assertThrows(SecurityException::class.java) { UsbProvisioning.requireShell(2000,true,"cosmic4","eu.sparkhat.aioa.companion") }
    }
    @Test fun realStoreClaimPersistsBeforeConsumerAndReopenCannotRepeatIt() {
        class MemoryDisk : UsbDeliveryPersistence {
            var disk=UsbDeliverySnapshot(null,false)
            var fail=false
            override fun read()=disk
            override fun write(snapshot: UsbDeliverySnapshot) { check(!fail);disk=snapshot }
        }
        val disk=MemoryDisk();val store=UsbProvisioningStore(disk);val input=raw()
        store.stage(input,identity,1001)
        disk.fail=true
        var effects=0
        assertThrows(Exception::class.java) { store.claim(identity,1001)?.let { effects++ } }
        assertEquals(0,effects);assertFalse(disk.disk.started)
        disk.fail=false
        store.claim(identity,1001)?.let { assertTrue(disk.disk.started);effects++ }
        assertEquals(1,effects)
        val reopened=UsbProvisioningStore(disk)
        assertNull(reopened.claim(identity,1002))
        assertNull(reopened.claim(identity,1400)) // expired/restart/ACK loss does not create a second effect
        assertEquals(1,effects)
        assertThrows(Exception::class.java) { reopened.stage(raw(JsonObject(payload()+("flow_id" to JsonPrimitive("9".repeat(32))))),identity,1002) }
    }
}
