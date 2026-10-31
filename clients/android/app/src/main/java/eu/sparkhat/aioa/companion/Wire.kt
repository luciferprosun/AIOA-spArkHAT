package eu.sparkhat.aioa.companion

import java.net.URI
import java.nio.charset.CodingErrorAction
import java.security.AlgorithmParameters
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import kotlinx.serialization.json.*

/** Neutral MobileMissionV1; signatures use DER ECDSA, not JWT r||s. */
object Wire {
    const val BASE = "/api/mobile/v1"
    const val HOST = "aioa.mobile.host-proof.v1"
    const val REQUEST = "aioa.mobile.request-proof.v1"
    const val ENROLL = "aioa.mobile.enrollment-proof.v1"
    const val OBSERVATION = "aioa.mobile.observation.v1"
    val hex32 = Regex("[0-9a-f]{32}")
    val hex64 = Regex("[0-9a-f]{64}")
    val sha40 = Regex("[0-9a-f]{40}")
    val taskId = Regex("meta-[0-9a-f]{32}")

    fun text(obj: JsonObject, key: String): String {
        val v = obj.getValue(key).jsonPrimitive
        require(v.isString)
        return v.content
    }
    fun integer(obj: JsonObject, key: String): Long {
        val v = obj.getValue(key).jsonPrimitive
        require(!v.isString)
        return v.long
    }
    fun flag(obj: JsonObject, key: String) = obj.getValue(key).jsonPrimitive.boolean
    fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes)
        .joinToString("") { "%02x".format(it.toInt() and 255) }
    fun b64(bytes: ByteArray): String = Base64.getEncoder().encodeToString(bytes)
    fun decode(value: String): ByteArray {
        require(value.length <= 1024)
        val raw = Base64.getDecoder().decode(value)
        require(b64(raw) == value)
        return raw
    }
    fun publicKey(value: String): ECPublicKey {
        val raw = decode(value)
        val key = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(raw)) as ECPublicKey
        val expected = AlgorithmParameters.getInstance("EC").apply {
            init(ECGenParameterSpec("secp256r1"))
        }.getParameterSpec(ECParameterSpec::class.java)
        require(key.params.curve == expected.curve && key.params.generator == expected.generator &&
            key.params.order == expected.order && key.params.cofactor == expected.cofactor && key.encoded.contentEquals(raw))
        return key
    }
    fun verify(spki: String, signature: String, value: JsonObject) {
        val verifier = Signature.getInstance("SHA256withECDSA")
        verifier.initVerify(publicKey(spki)); verifier.update(canonical(value))
        require(verifier.verify(decode(signature)))
    }
    private fun quote(s: String): String = buildString {
        append('"')
        s.forEach { c -> when (c) {
            '"' -> append("\\\""); '\\' -> append("\\\\"); '\b' -> append("\\b")
            '\u000c' -> append("\\f"); '\n' -> append("\\n"); '\r' -> append("\\r"); '\t' -> append("\\t")
            else -> if (c.code < 32) append("\\u%04x".format(c.code)) else append(c)
        } }
        append('"')
    }
    private fun render(value: JsonElement, depth: Int): String {
        require(depth <= 16)
        return when (value) {
            is JsonObject -> value.keys.sorted().joinToString(",", "{", "}") { quote(it)+":"+render(value.getValue(it), depth+1) }
            is JsonArray -> value.joinToString(",", "[", "]") { render(it, depth+1) }
            JsonNull -> "null"
            is JsonPrimitive -> if (value.isString) quote(value.content) else {
                val s = value.content
                require(s == "true" || s == "false" ||
                    (Regex("-?(0|[1-9][0-9]*)").matches(s) && s.toLong() in -9007199254740991L..9007199254740991L))
                s
            }
        }
    }
    fun canonical(value: JsonElement): ByteArray {
        val text = render(value, 0)
        val buffer = Charsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT)
            .encode(java.nio.CharBuffer.wrap(text))
        return ByteArray(buffer.remaining()).also { buffer.get(it) }
    }
    fun parse(raw: ByteArray): JsonObject {
        require(raw.size <= 65536)
        val parsed = Json.parseToJsonElement(raw.toString(Charsets.UTF_8)).jsonObject
        // Mobile responses are canonical UTF-8: also rejects duplicate keys,
        // nonminimal numbers/whitespace and malformed/unpaired Unicode.
        require(canonical(parsed).contentEquals(raw))
        return parsed
    }
    fun fresh(proof: JsonObject, now: Long) {
        val at = integer(proof, "issued_at"); val expires = integer(proof, "expires_at")
        require(at in (now-30)..(now+30) && expires > now && expires-at in 1L..30L)
    }
    fun origin(value: String): String {
        require(value.all { it.code in 33..126 })
        val u = URI(value); val h = u.host ?: error("HTTPS origin required")
        require(u.scheme == "https" && u.rawUserInfo == null && u.rawQuery == null && u.rawFragment == null &&
            u.rawPath.isNullOrEmpty() && '.' in h && !Regex("[0-9.]+").matches(h) && u.port != 443 &&
            (u.port == -1 || u.port in 1..65535) && h == h.lowercase())
        require(h.split('.').all { Regex("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?").matches(it) })
        require(value == "https://"+h+(if (u.port == -1) "" else ":${u.port}"))
        return value
    }
}
