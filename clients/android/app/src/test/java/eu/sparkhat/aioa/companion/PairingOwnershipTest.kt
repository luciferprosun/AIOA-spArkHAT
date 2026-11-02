package eu.sparkhat.aioa.companion

import org.junit.Assert.*
import org.junit.Test

/** Real ownership/persistence orchestration with fake storage/transport; no Android runtime needed. */
class PairingOwnershipTest {
    private class Memory : BindingPersistence {
        var value = BindingSnapshot(0,null)
        override fun read() = value
        override fun write(snapshot: BindingSnapshot) { value = snapshot }
    }
    private fun record(name: String) = PairingRecord(
        TrustedHost("https://$name.invalid","pin","spki","source","capsule","scope"),"request","digest",1234,true,true)

    @Test fun twoViewDeliveriesForgetRebindAndOlderResumeCannotRestoreOldHost() {
        val storage = Memory()
        val store = TrustedHostStore(storage)
        var oldTransportOpen = true
        val old = BindingOwner(store) { oldTransportOpen=false }
        val hostX = record("x")
        old.save(hostX)
        val delivered = mutableListOf<String>()
        // Cold and warm VIEW use the same delivery path; neither authorizes pairing.
        old.deliver("cold-packet") { delivered += it }
        old.deliver("warm-packet") { delivered += it }
        assertEquals(listOf("cold-packet","warm-packet"),delivered)
        assertEquals(hostX,store.snapshot().record)
        // Also defend a legacy second owner/process snapshot independently of singleTask.
        val newer = BindingOwner(TrustedHostStore(storage)) { }
        newer.forget()
        assertThrows(StaleBindingOwner::class.java) { old.requireCurrent() }
        assertFalse(oldTransportOpen)
        val hostY = record("y")
        newer.save(hostY)
        var staleReconnects = 0
        assertThrows(StaleBindingOwner::class.java) { old.requireCurrent(); staleReconnects++ }
        assertThrows(StaleBindingOwner::class.java) { old.save(hostX) }
        assertEquals(0,staleReconnects)
        assertEquals(hostY,store.snapshot().record)
        assertTrue(old.reconcile()) // returning older UI drops the old client and reloads Y
        assertEquals(hostY,old.record)
        assertFalse(oldTransportOpen)
    }
    @Test fun forgetAndSameHostRebindStillInvalidateOldRevisionAndInflightResult() {
        val store = TrustedHostStore(Memory())
        val first = BindingOwner(store) { }
        first.save(record("x"))
        var closes = 0
        val inflight = BindingOwner(store) { closes++ }
        inflight.requireCurrent()
        first.forget(); first.save(record("x"))
        assertThrows(StaleBindingOwner::class.java) { inflight.save(record("x")) }
        assertEquals(1,closes)
        assertTrue(store.snapshot().revision > 1)
    }
    @Test fun corruptBindingNeedsExplicitForgetBeforeNewConfirmation() {
        val storage = Memory().apply { value = BindingSnapshot(5,null,invalid=true) }
        val owner = BindingOwner(TrustedHostStore(storage)) { }
        assertTrue(owner.invalid)
        assertThrows(IllegalStateException::class.java) { owner.save(record("y")) }
        owner.forget()
        assertFalse(owner.invalid)
        owner.save(record("y"))
        assertEquals(7L,storage.value.revision)
    }

}
