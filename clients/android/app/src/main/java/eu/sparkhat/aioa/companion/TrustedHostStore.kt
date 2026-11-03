package eu.sparkhat.aioa.companion

import android.content.Context

/** Revision advances even on Forget, preventing a forget/rebind ABA from restoring an old bearer. */
data class BindingSnapshot(val revision: Long, val record: PairingRecord?, val invalid: Boolean = false)
interface BindingPersistence {
    fun read(): BindingSnapshot
    fun write(snapshot: BindingSnapshot)
}
class StaleBindingOwner : IllegalStateException("STALE_BINDING_OWNER")

/** App-private public metadata only. One process lock serializes all preference adapters. */
class TrustedHostStore(private val persistence: BindingPersistence) {
    constructor(context: Context) : this(object : BindingPersistence {
        private val prefs = context.getSharedPreferences("mobile-trusted-host-v1",Context.MODE_PRIVATE)
        override fun read(): BindingSnapshot {
            val revision = prefs.getLong("binding_revision",0)
            val raw = prefs.getString("public_binding",null)
            return try { BindingSnapshot(revision,raw?.let { PairingRecord.decode(it) }) }
            catch (_: Exception) { BindingSnapshot(revision,null,invalid=true) }
        }
        override fun write(snapshot: BindingSnapshot) {
            val edit = prefs.edit().putLong("binding_revision",snapshot.revision)
            if (snapshot.record == null) edit.remove("public_binding") else edit.putString("public_binding",snapshot.record.encode())
            check(edit.commit()) { "LOCAL_BINDING_SAVE_FAILED" }
        }
    })
    fun snapshot(): BindingSnapshot = synchronized(lock) { persistence.read() }
    fun replace(expected: BindingSnapshot, record: PairingRecord?): BindingSnapshot = synchronized(lock) {
        if (persistence.read() != expected) throw StaleBindingOwner()
        check(expected.revision < Long.MAX_VALUE)
        BindingSnapshot(expected.revision+1,record).also { persistence.write(it) }
    }
    companion object { private val lock = Any() }
}

/** Activity owner lease: stale reads close transport; writes compare the durable revision atomically. */
class BindingOwner(private val store: TrustedHostStore, private val closeTransport: () -> Unit) {
    private var snapshot = store.snapshot()
    val record get() = snapshot.record
    val invalid get() = snapshot.invalid
    fun requireCurrent() {
        check(!snapshot.invalid) { "HOST_BINDING_INVALID" }
        if (store.snapshot() != snapshot) { closeTransport(); throw StaleBindingOwner() }
    }
    fun reconcile(): Boolean {
        val latest = store.snapshot()
        if (latest == snapshot) return false
        closeTransport(); snapshot = latest
        return true
    }
    fun save(record: PairingRecord) {
        check(!snapshot.invalid) { "HOST_BINDING_INVALID" }
        try { snapshot = store.replace(snapshot,record) }
        catch (failure: StaleBindingOwner) { closeTransport(); throw failure }
    }
    fun forget() {
        try { snapshot = store.replace(snapshot,null); closeTransport() }
        catch (failure: StaleBindingOwner) { closeTransport(); throw failure }
    }
    fun <T> deliver(packet: String, importPacket: (String) -> T): T {
        reconcile()
        return importPacket(packet)
    }
}
