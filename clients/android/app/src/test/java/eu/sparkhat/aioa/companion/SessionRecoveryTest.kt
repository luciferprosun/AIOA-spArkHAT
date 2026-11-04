package eu.sparkhat.aioa.companion

import java.io.IOException
import java.net.ConnectException
import java.security.SignatureException
import javax.net.ssl.SSLHandshakeException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

/** Offline sequencing tests. The real MobileClient owns cryptographic verification. */
class SessionRecoveryTest {
    private fun record(trusted: Boolean = true) = PairingRecord(
        TrustedHost("https://host.invalid","pin","spki","source","capsule","scope"),
        "request","digest",1,true,trusted)
    private class Hints : RecoveryCheckpoint {
        val pending = mutableSetOf<String>()
        private val pauses = mutableSetOf<String>()
        override fun pending(binding: String) = binding in pending
        override fun mark(binding: String) { pending += binding }
        override fun clear(binding: String) { pending -= binding }
        override fun paused(binding: String) = binding in pauses
        override fun pause(binding: String) { pauses += binding }
        override fun resume(binding: String) { pauses -= binding }
    }
    private class Port : SessionRecoveryPort<String> {
        var session = false
        val calls = mutableListOf<String>()
        var prepareError: Exception? = null
        var reconnectError: Exception? = null
        var statusError: Exception? = null
        var statusFailures = 0
        override fun hasSession() = session
        override suspend fun prepare(host: TrustedHost): TrustedHost {
            calls += "host-proof"; prepareError?.let { throw it }; return host
        }
        override suspend fun reconnect() {
            calls += "session-posts"; reconnectError?.let { throw it }; session=true
        }
        override suspend fun status(): String {
            calls += "signed-status"
            if (statusFailures-- > 0) throw statusError ?: IOException("offline test")
            statusError?.let { if (statusFailures == -1) throw it }
            return "verified-readback"
        }
    }
    private fun recovery(port: Port, hints: Hints, waits: MutableList<Long> = mutableListOf(),
        guard: () -> Unit = {}) = SessionRecovery(port,hints,pause={ waits += it },guard=guard)

    @Test fun expiredInvitationDoesNotExpireTrustedBindingAndAcceptanceIsExplicit() = runBlocking {
        val p=Port(); val h=Hints(); val r=recovery(p,h)
        val result=r.recover(record(),manual=false,networkAvailable=true)
        assertEquals(listOf("host-proof","session-posts","signed-status"),p.calls)
        assertEquals("verified-readback",result.observation)
        assertTrue(h.pending.isNotEmpty()) // no local success before owner/readback acceptance
        r.accept(result)
        assertTrue(h.pending.isEmpty())
    }
    @Test fun pendingPairingCannotAutomaticallyCompleteOrGrantApproval() = runBlocking {
        val p=Port();val r=recovery(p,Hints())
        try { r.recover(record(false),false,true);fail("unapproved binding") } catch (_: RecoveryNeedsManual) { }
        assertTrue(p.calls.isEmpty())
    }
    @Test fun liveMemorySessionUsesOnlySignedReadAndExpiredSessionUsesExistingReconnect() = runBlocking {
        val p=Port().apply { session=true };val r=recovery(p,Hints())
        r.recover(record(),false,true)
        assertEquals(listOf("signed-status"),p.calls)
        p.session=false;p.calls.clear()
        r.recover(record(),false,true)
        assertEquals(listOf("host-proof","session-posts","signed-status"),p.calls)
    }
    @Test fun offlineSendsNothingAndOnlineCanRecoverWithoutInvitation() = runBlocking {
        val p=Port();val r=recovery(p,Hints())
        try { r.recover(record(),false,false);fail("offline") } catch (_: RecoveryNetworkUnavailable) { }
        assertTrue(p.calls.isEmpty())
        r.recover(record(),false,true)
        assertEquals(1,p.calls.count { it=="session-posts" })
    }
    @Test fun rejectedExpiredMemoryTokenCreatesAtMostOneFreshSessionSequence() = runBlocking {
        val p=Port().apply { session=true;statusError=ExpiredTransportSession() }
        recovery(p,Hints()).recover(record(),false,true)
        assertEquals(listOf("signed-status","host-proof","session-posts","signed-status"),p.calls)
    }
    @Test fun lostSessionAckIsNeverAutomaticallyReplayedIncludingAfterProcessRestart() = runBlocking {
        val p=Port().apply { reconnectError=IOException("lost ACK") };val h=Hints()
        try { recovery(p,h).recover(record(),false,true);fail("lost ACK") } catch (_: IOException) { }
        val restarted=Port()
        try { recovery(restarted,h).recover(record(),false,true);fail("must ask for manual recovery") }
        catch (_: RecoveryNeedsManual) { }
        assertEquals(1,p.calls.count { it=="session-posts" });assertTrue(restarted.calls.isEmpty())
        recovery(restarted,h).recover(record(),manual=true,networkAvailable=true)
        assertEquals(1,restarted.calls.count { it=="session-posts" })
    }
    @Test fun hostMismatchTlsAndRevokedAccessDoNotRetry() = runBlocking {
        for (error in listOf(IllegalStateException("HOST_BINDING_CHANGED"),SSLHandshakeException("test"))) {
            val p=Port().apply { prepareError=error };val h=Hints();val waits=mutableListOf<Long>()
            try { recovery(p,h,waits).recover(record(),false,true);fail("host failure") } catch (_: Exception) { }
            assertEquals(listOf("host-proof"),p.calls);assertTrue(h.pending.isEmpty());assertTrue(waits.isEmpty())
        }
        val p=Port().apply { reconnectError=IllegalStateException("SCOPE_DENIED") };val h=Hints()
        try { recovery(p,h).recover(record(),false,true);fail("revoked") } catch (_: IllegalStateException) { }
        assertEquals(1,p.calls.count { it=="session-posts" });assertTrue(h.pending.isNotEmpty())
    }
    @Test fun safeReadsHaveExactlyOneBackoffAndNoMutationRetry() = runBlocking {
        val p=Port().apply { session=true;statusFailures=1 };val waits=mutableListOf<Long>()
        recovery(p,Hints(),waits).recover(record(),false,true)
        assertEquals(listOf("signed-status","signed-status"),p.calls)
        assertEquals(listOf(1000L),waits)
        val offline=Port().apply { prepareError=ConnectException("test") };waits.clear()
        try { recovery(offline,Hints(),waits).recover(record(),false,true);fail("offline") } catch (_: ConnectException) { }
        assertEquals(listOf("host-proof","host-proof"),offline.calls);assertEquals(listOf(1000L),waits)
    }
    @Test fun invalidSignedReadbackDoesNotClearUncertaintyOrClaimConnected() = runBlocking {
        val p=Port().apply { statusError=SignatureException("invalid signature") };val h=Hints()
        try { recovery(p,h).recover(record(),false,true);fail("bad proof") } catch (_: SignatureException) { }
        assertTrue(h.pending.isNotEmpty());assertEquals(1,p.calls.count { it=="signed-status" })
    }
    @Test fun cancellationAfterPostCheckpointSurvivesAndIsNotRetried() = runBlocking {
        val p=Port().apply { reconnectError=CancellationException("background") };val h=Hints()
        try { recovery(p,h).recover(record(),false,true);fail("cancelled") } catch (_: CancellationException) { }
        assertTrue(h.pending.isNotEmpty());assertEquals(1,p.calls.count { it=="session-posts" })
    }
    @Test fun changedOwnerCannotAcceptAnOldReadbackOrClearItsCheckpoint() = runBlocking {
        var current=true;val p=Port();val h=Hints();val r=recovery(p,h,guard={ check(current) })
        val result=r.recover(record(),false,true);current=false
        assertThrows(IllegalStateException::class.java) { r.accept(result) }
        assertTrue(h.pending.isNotEmpty())
    }
    @Test fun foregroundAndNetworkCallbacksAreBoundedAndUncertaintyNeedsManualAction() {
        val gate=RecoveryWakeGate();gate.foreground(true)
        assertFalse(gate.claim(trusted=true,online=false,busy=false,uncertain=false))
        assertFalse(gate.claim(true,true,true,false))
        assertTrue(gate.claim(true,true,false,false));assertTrue(gate.claim(true,true,false,false))
        assertFalse(gate.claim(true,true,false,false))
        gate.foreground(true);assertFalse(gate.claim(true,true,false,false)) // duplicate resume cannot reset budget
        gate.foreground(false);assertFalse(gate.claim(true,true,false,false))
        gate.foreground(true);assertFalse(gate.claim(true,true,false,true))
        assertFalse(gate.claim(false,true,false,false));assertTrue(gate.claim(true,true,false,false))
    }
    @Test fun ordinaryReadCompletionReleasesBusyAndDrainsRecoveryAfterNetworkLoss() {
        val work=RecoveryWorkQueue();val oldRead=Any();val recovery=Any()
        work.start(oldRead);work.defer()
        assertTrue(work.busy)
        assertTrue(work.finish(oldRead)) // irrespective of invalidated freshness generation
        assertFalse(work.busy)
        work.start(recovery)
        assertFalse(work.finish(oldRead)) // late old callback cannot release the new job
        assertTrue(work.busy)
        assertFalse(work.finish(recovery));assertFalse(work.busy)
    }
    @Test fun initialCapabilitiesCallbackDoesNotSpendRealNetworkRecoveryBudget() {
        val connectivity=RecoveryConnectivity(true,1L);val gate=RecoveryWakeGate();gate.foreground(true)
        assertTrue(gate.claim(true,true,false,false)) // resume starts one recovery
        assertFalse(connectivity.update(true,1L)) // matching initial callback is coalesced
        assertFalse(connectivity.update(true,1L))
        gate.accepted() // a verified readback ends this bounded recovery episode
        assertTrue(connectivity.update(false,null))
        assertFalse(gate.claim(true,false,false,false))
        assertTrue(connectivity.update(true,2L)) // actual network return gets a recovery
        assertTrue(gate.claim(true,true,false,false))
        assertFalse(connectivity.update(true,2L))
        assertTrue(connectivity.update(true,3L)) // VPN/default route changed while Internet stayed available
    }
    @Test fun explicitSessionRevocationIntentIsNotUndoneByAutomaticRecoveryAfterRestart() = runBlocking {
        val h=Hints();val key=SessionRecovery.binding(record());h.pause(key)
        for (memoryToken in listOf(false,true)) {
            val p=Port().apply { session=memoryToken };val restarted=recovery(p,h)
            try { restarted.recover(record(),false,true);fail("explicit pause must survive restart") }
            catch (_: RecoveryNeedsManual) { }
            assertTrue(p.calls.isEmpty());assertTrue(h.paused(key))
        }
        val p=Port();val r=recovery(p,h)
        val result=r.recover(record(),manual=true,networkAvailable=true);r.accept(result)
        assertFalse(h.paused(key));assertEquals(1,p.calls.count { it=="session-posts" })
    }
}
