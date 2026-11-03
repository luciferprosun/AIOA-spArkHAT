package eu.sparkhat.aioa.companion

import java.io.InterruptedIOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.security.SignatureException
import javax.net.ssl.SSLException

/** Display-only diagnosis. Never grants authority, retries or reports success. */
internal enum class PairingProblem {
    DNS, NETWORK, TIMEOUT, TLS, EXPIRED, BINDING_CHANGED, SOURCE_CHANGED, PROOF, DENIED, UNKNOWN;

    companion object {
        fun from(failure: Exception): PairingProblem = when {
            failure is UnknownHostException -> DNS
            failure is SocketTimeoutException || failure is InterruptedIOException -> TIMEOUT
            failure is SSLException -> TLS
            failure is ConnectException || failure is NoRouteToHostException || failure is SocketException -> NETWORK
            failure is SignatureException -> PROOF
            failure.message == "INVITE_EXPIRED" -> EXPIRED
            failure.message == "HOST_BINDING_CHANGED" -> BINDING_CHANGED
            failure.message == "HOST_SOURCE_CHANGED" -> SOURCE_CHANGED
            failure.message == "SIGNED_RESPONSE_MISMATCH" || failure.message == "INVALID_SIGNATURE" -> PROOF
            failure.message == "SCOPE_DENIED" -> DENIED
            else -> UNKNOWN
        }
    }
}
