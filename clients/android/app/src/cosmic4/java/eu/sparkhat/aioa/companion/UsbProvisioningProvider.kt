package eu.sparkhat.aioa.companion

import android.content.ContentProvider
import android.content.ContentValues
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.database.Cursor
import android.net.Uri
import android.os.Binder
import android.os.Bundle
import java.util.Base64
import kotlinx.serialization.json.*

/** Debug USB installation aid. Kernel shell UID only; no transport or approval endpoint. */
class UsbProvisioningProvider : ContentProvider() {
    override fun onCreate()=true
    @Suppress("DEPRECATION")
    private fun identity(): UsbIdentity {
        val ctx=requireNotNull(context)
        val info=ctx.packageManager.getPackageInfo(ctx.packageName,PackageManager.GET_SIGNATURES)
        val signers=requireNotNull(info.signatures)
        require(signers.size==1)
        return UsbIdentity(ctx.packageName,Wire.sha(signers.single().toByteArray()),BuildConfig.AIOA_SOURCE_SHA,TransportIdentity().spki)
    }
    override fun call(method: String, arg: String?, extras: Bundle?): Bundle {
        val ctx=requireNotNull(context)
        UsbProvisioning.requireShell(Binder.getCallingUid(),ctx.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE!=0,
            BuildConfig.BUILD_TYPE,ctx.packageName)
        require(extras==null || extras.isEmpty)
        val identity=identity(); val now=System.currentTimeMillis()/1000
        require(Wire.sha40.matches(identity.source)) { "APK_SOURCE_UNBOUND" }
        val store=androidUsbProvisioningStore(ctx)
        val result=when(method) {
            "identity" -> {
                require(arg!=null && Wire.hex64.matches(arg))
                val proof=buildJsonObject {
                    put("schema","aioa.mobile.usb-identity.v1"); put("challenge",arg); put("issued_at",now)
                    put("package",identity.packageName); put("certificate_sha256",identity.certificate)
                    put("apk_source_sha",identity.source); put("device_spki",identity.spki)
                }
                buildJsonObject { put("proof",proof); put("signature",TransportIdentity().sign(proof)) }
            }
            "stage" -> {
                require(arg!=null && arg.length<=22000 && Regex("[A-Za-z0-9_-]+").matches(arg))
                val decoded=Base64.getUrlDecoder().decode(arg)
                require(Base64.getUrlEncoder().withoutPadding().encodeToString(decoded)==arg)
                val current=TrustedHostStore(ctx).snapshot()
                require(!current.invalid && current.record==null) { "ALREADY_CONFIGURED" }
                store.stage(decoded.toString(Charsets.UTF_8),identity,now)
                store.publicState()
            }
            "state" -> {
                require(arg==null)
                val snapshot=TrustedHostStore(ctx).snapshot()
                buildJsonObject {
                    put("schema","aioa.mobile.usb-state.v1"); put("device_spki",identity.spki); put("apk_source_sha",identity.source)
                    put("delivery",store.publicState()); put("binding_invalid",snapshot.invalid)
                    put("pairing",snapshot.record?.let { Wire.parse(it.encode().toByteArray()) } ?: JsonNull)
                    put("status_readback",UsbReadback.publicState())
                }
            }
            else -> throw SecurityException("USB_METHOD_DENIED")
        }
        return Bundle().apply { putString("json_b64",Base64.getUrlEncoder().withoutPadding().encodeToString(Wire.canonical(result))) }
    }
    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor? = throw SecurityException("USB_METHOD_DENIED")
    override fun getType(uri: Uri): String? = throw SecurityException("USB_METHOD_DENIED")
    override fun insert(uri: Uri, values: ContentValues?): Uri? = throw SecurityException("USB_METHOD_DENIED")
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = throw SecurityException("USB_METHOD_DENIED")
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = throw SecurityException("USB_METHOD_DENIED")
}
