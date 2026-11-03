package eu.sparkhat.aioa.companion

import java.io.IOException
import javax.net.ssl.SSLException
import kotlinx.coroutines.delay

/** These are local UI/retry hints, never credentials or Core authority. */
internal interface RecoveryCheckpoint {
    fun pending(binding: String): Boolean
    fun mark(binding: String)
    fun clear(binding: String)
    fun paused(binding: String): Boolean
    fun pause(binding: String)
    fun resume(binding: String)
}

internal interface SessionRecoveryPort<T> {
    fun hasSession(): Boolean
    suspend fun prepare(host: TrustedHost): TrustedHost
    suspend fun reconnect()
    suspend fun status(): T
}

open class ExpiredTransportSession : IllegalStateException("FRESH_ENROLLMENT_REQUIRED")
internal class RecoveryNeedsManual : IllegalStateException("MANUAL_SESSION_READBACK_REQUIRED")
internal class RecoveryNetworkUnavailable : IOException("WAITING_FOR_NETWORK")
internal data class RecoveryReadback<T>(val host: TrustedHost, val observation: T, val checkpoint: String)

/** Sequences existing client operations; has no pairing/approval/WRITE port. */
internal class SessionRecovery<T>(
    private val transport: SessionRecoveryPort<T>,
    private val checkpoint: RecoveryCheckpoint,
    private val pause: suspend (Long) -> Unit = { delay(it) },
    private val guard: () -> Unit = {}
) {
    companion object {
        fun binding(record: PairingRecord) = Wire.sha(record.encode().toByteArray(Charsets.UTF_8))
    }

    suspend fun recover(record: PairingRecord, manual: Boolean, networkAvailable: Boolean): RecoveryReadback<T> {
        guard()
        if (!record.trusted && !(manual && record.completeAttempted)) throw RecoveryNeedsManual()
        if (!networkAvailable) throw RecoveryNetworkUnavailable()
        val key = binding(record)
        if (!manual && checkpoint.paused(key)) throw RecoveryNeedsManual()
        if (manual) checkpoint.resume(key)
        // A live memory-only token can reconcile an interrupted signed read.
        // It cannot repeat any session mutation, even when a POST hint exists.
        if (transport.hasSession()) {
            try { return RecoveryReadback(record.host,read { transport.status() },key) }
            catch (_: ExpiredTransportSession) { /* One new, guarded session sequence below. */ }
        }
        if (!manual && checkpoint.pending(key)) throw RecoveryNeedsManual()
        val host = read { transport.prepare(record.host) }
        guard()
        // Durable local uncertainty precedes both session POSTs. Lost ACK,
        // cancellation or process death leaves this for explicit recovery.
        checkpoint.mark(key)
        guard()
        transport.reconnect() // exactly one sequence, no automatic POST retry
        guard()
        return RecoveryReadback(host,read { transport.status() },key)
    }

    fun accept(result: RecoveryReadback<T>) {
        guard()
        checkpoint.clear(result.checkpoint)
    }

    private suspend fun <R> read(block: suspend () -> R): R {
        for (attempt in 0..1) {
            guard()
            try { return block().also { guard() } }
            catch (failure: IOException) {
                if (failure is SSLException || attempt == 1) throw failure
                // The caller creates fresh proofs/nonces on every safe read.
                pause(1000)
            }
        }
        error("UNREACHABLE")
    }
}

/** Limits automatic foreground/network wakeups; the existing task lock owns single flight. */
internal class RecoveryWakeGate {
    private var visible = false
    private var attempts = 0
    fun foreground(active: Boolean) {
        if (active && !visible) attempts=0
        visible=active
    }
    fun claim(trusted: Boolean, online: Boolean, busy: Boolean, uncertain: Boolean): Boolean {
        if (!visible || !trusted || !online || busy || uncertain || attempts >= 2) return false
        attempts++
        return true
    }
    fun accepted() { attempts=0 }
}

/** Local coroutine ownership: cleanup never depends on a stale proof generation. */
internal class RecoveryWorkQueue {
    private val active = mutableSetOf<Any>()
    private var deferred = false
    val busy get() = active.isNotEmpty()
    fun start(ticket: Any) { check(active.add(ticket)) }
    fun defer() { deferred=true }
    fun finish(ticket: Any): Boolean {
        if (!active.remove(ticket) || busy) return false
        return deferred.also { deferred=false }
    }
}

/** Coalesce initial/repeated callbacks, but retain real default-route changes. */
internal class RecoveryConnectivity(var available: Boolean, var identity: Long?) {
    fun update(online: Boolean, network: Long?): Boolean {
        if (available == online && identity == network) return false
        available=online;identity=network
        return true
    }
}
