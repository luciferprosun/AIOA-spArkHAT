package eu.sparkhat.aioa.companion

import java.security.KeyPairGenerator
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.Base64
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

/** Behavior tests written before implementation. Execution requires the qualified JVM gate. */
class PairingProtocolTest {
    private val key = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
    private val spki = Wire.b64(key.public.encoded)
    private fun signed(value: JsonObject) = Wire.b64(Signature.getInstance("SHA256withECDSA").run {
        initSign(key.private); update(Wire.canonical(value)); sign()
    })
    private fun packet(expires: Long = 1300): JsonObject {
        val invite = buildJsonObject {
            put("schema","aioa.mobile.pairing-invite.v1"); put("invite_id","a".repeat(32))
            put("origin","https://fixture.invalid"); put("host_spki",spki); put("audience",Wire.sha(key.public.encoded))
            put("tls_spki_pin","sha256/"+Wire.b64(ByteArray(32))); put("source_sha","b".repeat(40))
            put("capsule_digest","c".repeat(64)); put("owner_scope_digest","d".repeat(64))
            put("issued_at",1000); put("expires_at",expires)
        }
        return buildJsonObject { put("invite",invite); put("signature",signed(invite)) }
    }
    @Test fun rawPacketAndSafeLinkResolveToSameHost() {
        val raw = Wire.canonical(packet())
        val link = "aioa://pair#"+Base64.getUrlEncoder().withoutPadding().encodeToString(raw)
        assertEquals(PairingProtocol.parseInvite(raw.toString(Charsets.UTF_8),1001),PairingProtocol.parseInvite(link,1001))
    }
    @Test fun rejectsUrlsAmbiguousEncodingDuplicatesExpiredAndFuturePackets() {
        val raw = Wire.canonical(packet()).toString(Charsets.UTF_8)
        for (bad in listOf("https://fixture.invalid/invite", "aioa://pair/path#e30", "aioa://pair?x=y#e30",
            "aioa://pair#e30=", raw.replace("\"invite\":", "\"signature\":\"bad\",\"invite\":"))) {
            assertThrows(Exception::class.java) { PairingProtocol.parseInvite(bad,1001) }
        }
        assertThrows(Exception::class.java) { PairingProtocol.parseInvite(raw,1300) }
        assertThrows(Exception::class.java) { PairingProtocol.parseInvite(raw,999) }
        assertThrows(Exception::class.java) { PairingProtocol.parseInvite(Wire.canonical(packet(1301)).toString(Charsets.UTF_8),1001) }
    }
    @Test fun forgedSignatureAndChangedScopeFail() {
        val raw = Wire.canonical(packet()).toString(Charsets.UTF_8)
        assertThrows(Exception::class.java) { PairingProtocol.parseInvite(raw.replace("d".repeat(64),"e".repeat(64)),1001) }
        val host = PairingProtocol.parseInvite(raw,1001).host
        assertThrows(Exception::class.java) { host.requireSameBinding(host.copy(ownerScope="e".repeat(64))) }
        host.requireSameBinding(host.copy(source="e".repeat(40),capsule="f".repeat(64)))
    }
    @Test fun signedResponseBindsFullRequestAndRejectsRevokedRecovery() {
        val host = PairingProtocol.parseInvite(Wire.canonical(packet()).toString(Charsets.UTF_8),1001).host
        val request = buildJsonObject { put("nonce","e".repeat(32)); put("signature","device-signature") }
        val data = buildJsonObject { put("state","REVOKED") }
        val proof = buildJsonObject {
            put("schema","aioa.mobile.pairing-response.v1"); put("method","POST"); put("path",Wire.BASE+"/pairing/status")
            put("request_sha256",Wire.sha(Wire.canonical(request))); put("nonce","e".repeat(32))
            put("audience",host.audience); put("origin",host.origin); put("source_sha",host.source)
            put("capsule_digest",host.capsule); put("owner_scope_digest",host.ownerScope)
            put("issued_at",1001); put("expires_at",1031); put("data_sha256",Wire.sha(Wire.canonical(data)))
        }
        val envelope = buildJsonObject { put("ok",true); put("data",data); put("proof",proof); put("signature",signed(proof)) }
        assertEquals(data,PairingProtocol.verifyResponse(envelope,request,"/pairing/status",host,1002))
        assertThrows(Exception::class.java) { PairingProtocol.verifyResponse(envelope,request,"/pairing/complete",host,1002) }
        assertThrows(Exception::class.java) { PairingProtocol.verifyResponse(envelope,JsonObject(request+("nonce" to JsonPrimitive("f".repeat(32)))),"/pairing/status",host,1002) }
        assertThrows(Exception::class.java) { PairingProtocol.verifyResponse(envelope,request,"/pairing/status",host,1031) }
        assertFalse(PairingProtocol.canComplete("REVOKED",false))
        assertFalse(PairingProtocol.canComplete("APPROVED",true)) // uncertain complete is never replayed
        assertTrue(PairingProtocol.canComplete("APPROVED",false))
        assertFalse(PairingProtocol.canComplete("COMPLETED",false))
    }
    @Test fun trustSnapshotHasOnlyPublicDataAndPreservesRecoveryDigest() {
        val invite = PairingProtocol.parseInvite(Wire.canonical(packet()).toString(Charsets.UTF_8),1001)
        val record = PairingRecord(invite.host,"a".repeat(32),"b".repeat(64),1300,true,false)
        assertEquals(record,PairingRecord.decode(record.encode()))
        assertFalse(record.encode().contains("token"))
        assertEquals("b".repeat(64),PairingRecord.decode(record.encode()).requestDigest)
        assertEquals("000001",PairingProtocol.sas("00000001"+"0".repeat(56)))
    }
    @Test fun reconnectChallengeRejectsOtherDeviceExpiredAndExtraFields() {
        val device = "a".repeat(64)
        val challenge = buildJsonObject {
            put("device_id",device); put("challenge_id","b".repeat(32))
            put("challenge_nonce","c".repeat(32)); put("expires_at",1060)
        }
        PairingProtocol.validateChallenge(challenge,device,1000)
        assertThrows(Exception::class.java) { PairingProtocol.validateChallenge(challenge,"d".repeat(64),1000) }
        assertThrows(Exception::class.java) { PairingProtocol.validateChallenge(challenge,device,1060) }
        assertThrows(Exception::class.java) { PairingProtocol.validateChallenge(JsonObject(challenge+("token" to JsonPrimitive("unexpected"))),device,1000) }
    }
    @Test fun signedStatusMustMatchPersistedRequestAndSasEvenWhenRevoked() {
        val invite = PairingProtocol.parseInvite(Wire.canonical(packet()).toString(Charsets.UTF_8),1001)
        val record = PairingRecord(invite.host,"a".repeat(32),"b".repeat(64),1300,true,false)
        val device = "d".repeat(64)
        val status = buildJsonObject {
            put("request_id",record.requestId); put("request_digest",record.requestDigest); put("device_id",device)
            put("device_name","AIOA Android"); put("sas",PairingProtocol.sas(record.requestDigest))
            put("state","REVOKED"); put("expires_at",1300); put("automatic_retry",false)
        }
        assertEquals("REVOKED",PairingProtocol.validateStatus(status,record,device))
        assertThrows(Exception::class.java) { PairingProtocol.validateStatus(JsonObject(status+("sas" to JsonPrimitive("000000"))),record,device) }
        assertThrows(Exception::class.java) { PairingProtocol.validateStatus(status,record.copy(requestId="e".repeat(32)),device) }
        assertThrows(Exception::class.java) { PairingProtocol.validateStatus(JsonObject(status+("automatic_retry" to JsonPrimitive("false"))),record,device) }
    }

}
