package eu.sparkhat.aioa.companion

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import kotlinx.serialization.json.JsonObject

/** Transport identity only. Private material is never exported or backed up. */
class TransportIdentity {
    private val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    private val alias = "aioa-mobile-p256-v1"
    init {
        if (!store.containsAlias(alias)) {
            KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply {
                initialize(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN)
                    .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                    .setDigests(KeyProperties.DIGEST_SHA256).setUserAuthenticationRequired(false).build())
            }.generateKeyPair()
        }
    }
    val spki: String get() = Wire.b64(store.getCertificate(alias).publicKey.encoded)
    fun sign(value: JsonObject): String {
        val signer = Signature.getInstance("SHA256withECDSA")
        signer.initSign(store.getKey(alias, null) as PrivateKey)
        signer.update(Wire.canonical(value)); return Wire.b64(signer.sign())
    }
}
