package eu.sparkhat.aioa.companion

/** A delivery event reveals accepted confirmation; ordinary recomposition never changes navigation. */
internal fun routePairingDelivery(raw: String, deliver: (String) -> Boolean,
    showConfirmation: () -> Unit, consumed: () -> Unit) {
    if (deliver(raw)) showConfirmation()
    consumed()
}
