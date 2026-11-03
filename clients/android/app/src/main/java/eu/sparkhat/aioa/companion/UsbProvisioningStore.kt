package eu.sparkhat.aioa.companion

import android.content.Context
import kotlinx.serialization.json.*

/** Android adapter uses one synchronous SharedPreferences commit for payload + claim. */
fun androidUsbProvisioningStore(context: Context)=UsbProvisioningStore(object : UsbDeliveryPersistence {
    private val prefs=context.getSharedPreferences("mobile-usb-delivery-v1",0)
    override fun read()=UsbDeliverySnapshot(prefs.getString("payload",null),prefs.getBoolean("started",false))
    override fun write(snapshot: UsbDeliverySnapshot) {
        check(prefs.edit().putString("payload",snapshot.payload).putBoolean("started",snapshot.started).commit()) { "LOCAL_BINDING_SAVE_FAILED" }
    }
})

/** Process-memory evidence set only after the existing client and ViewModel accept signed status. */
object UsbReadback {
    private var receipt: MobileObservation?=null
    @Synchronized fun clear() { receipt=null }
    @Synchronized fun accept(observation: MobileObservation) {
        receipt=observation.takeIf { it.proof?.get("path")?.jsonPrimitive?.content==Wire.BASE+"/status" && it.signature!=null }
    }
    @Synchronized fun publicState(): JsonElement {
        val r=receipt?.takeIf { Freshness.elapsedMs()<it.validUntilElapsedMs } ?: return JsonNull
        return buildJsonObject { put("proof",r.proof!!); put("signature",r.signature!!); put("fresh",true) }
    }
}
