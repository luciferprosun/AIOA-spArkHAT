package eu.sparkhat.aioa.companion

import java.io.IOException
import java.io.InterruptedIOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.security.SignatureException
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.SSLPeerUnverifiedException
import kotlinx.serialization.json.*
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class PairingProblemTest {
    @Test fun missingPrivateDnsIdentifiesTheTailscalePrerequisite() {
        assertEquals(PairingProblem.DNS, PairingProblem.from(UnknownHostException("private host")))
    }

    @Test fun connectionRefusalAndMissingRouteRemainNetworkFailures() {
        for (failure in listOf(ConnectException(), NoRouteToHostException())) {
            assertEquals(PairingProblem.NETWORK, PairingProblem.from(failure))
        }
    }

    @Test fun connectReadAndWholeCallTimeoutsHaveAnExplicitDiagnostic() {
        for (failure in listOf(SocketTimeoutException(), InterruptedIOException("timeout"))) {
            assertEquals(PairingProblem.TIMEOUT, PairingProblem.from(failure))
        }
    }

    @Test fun rejectedTlsNeverSuggestsBypassingTheCertificateOrPin() {
        for (failure in listOf(SSLHandshakeException("certificate"), SSLPeerUnverifiedException("pin"))) {
            assertEquals(PairingProblem.TLS, PairingProblem.from(failure))
        }
    }

    @Test fun expiredInviteAndChangedSourceAreDistinguished() {
        assertEquals(PairingProblem.EXPIRED, PairingProblem.from(IllegalArgumentException("INVITE_EXPIRED")))
        assertEquals(PairingProblem.SOURCE_CHANGED, PairingProblem.from(IllegalArgumentException("HOST_SOURCE_CHANGED")))
        assertEquals(PairingProblem.BINDING_CHANGED, PairingProblem.from(IllegalArgumentException("HOST_BINDING_CHANGED")))
    }

    @Test fun rejectedSignedProofAndScopeAreNotReportedAsNetworkTimeouts() {
        assertEquals(PairingProblem.PROOF, PairingProblem.from(SignatureException("untrusted text")))
        assertEquals(PairingProblem.PROOF, PairingProblem.from(IllegalArgumentException("SIGNED_RESPONSE_MISMATCH")))
        assertEquals(PairingProblem.DENIED, PairingProblem.from(IllegalStateException("SCOPE_DENIED")))
    }

    @Test fun arbitraryExceptionTextCannotChooseARecognizedDiagnostic() {
        assertEquals(PairingProblem.UNKNOWN, PairingProblem.from(IOException("token=private; SSLHandshakeException")))
        assertEquals(PairingProblem.UNKNOWN, PairingProblem.from(IllegalStateException("untrusted INVITE_EXPIRED text")))
    }

    @Test fun classifierDoesNotConvertUnknownOutcomesIntoRetryOrSuccess() {
        assertEquals(PairingProblem.UNKNOWN, PairingProblem.from(IllegalStateException("UNKNOWN_READBACK_REQUIRED")))
        assertEquals(PairingProblem.UNKNOWN, PairingProblem.from(IllegalStateException("READBACK_REQUIRED")))
    }

    @Test fun actualWireSignatureRejectionHasAnExplicitProofDiagnostic() {
        val raw = javaClass.classLoader!!.getResourceAsStream("mobile_wire_vector.json")!!.bufferedReader().readText()
        val vector = Json.parseToJsonElement(raw).jsonObject
        val proof = vector.getValue("proof").jsonObject
        Wire.verify(Wire.text(vector,"spki"), Wire.text(vector,"signature"), proof)
        val changed = JsonObject(proof + ("nonce" to JsonPrimitive("0".repeat(32))))
        val failure = assertThrows(IllegalArgumentException::class.java) {
            Wire.verify(Wire.text(vector,"spki"), Wire.text(vector,"signature"), changed)
        }
        assertEquals(PairingProblem.PROOF, PairingProblem.from(failure))
    }
}
