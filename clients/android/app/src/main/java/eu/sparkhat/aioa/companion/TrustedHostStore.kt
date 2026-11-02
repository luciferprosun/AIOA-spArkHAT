package eu.sparkhat.aioa.companion

import android.content.Context

/** App-private, backup-excluded public binding. Bearer and challenges never enter this store. */
class TrustedHostStore(context: Context) {
    private val prefs = context.getSharedPreferences("mobile-trusted-host-v1",Context.MODE_PRIVATE)
    fun load(): PairingRecord? = prefs.getString("public_binding",null)?.let { PairingRecord.decode(it) }
    fun save(record: PairingRecord) {
        check(prefs.edit().putString("public_binding",record.encode()).commit()) { "LOCAL_BINDING_SAVE_FAILED" }
    }
    fun forget() { check(prefs.edit().remove("public_binding").commit()) { "LOCAL_BINDING_SAVE_FAILED" } }
}
