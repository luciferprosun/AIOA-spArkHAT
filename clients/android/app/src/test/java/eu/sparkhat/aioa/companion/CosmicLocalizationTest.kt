package eu.sparkhat.aioa.companion

import java.io.File
import java.util.Locale
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.*
import org.junit.Test

/** Resource-contract regression tests; actual locale/TalkBack layout remains a device gate. */
class CosmicLocalizationTest {
    private fun strings(language: String): Map<String,String> {
        val directories = generateSequence(File(System.getProperty("user.dir"))) { it.parentFile }
        val file = directories.flatMap { sequenceOf(File(it,"src/main/res/$language/strings.xml"),
            File(it,"clients/android/app/src/main/res/$language/strings.xml")) }.first { it.isFile }
        val factory = DocumentBuilderFactory.newInstance()
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl",true)
        val nodes = factory.newDocumentBuilder().parse(file).getElementsByTagName("string")
        return (0 until nodes.length).associate { index ->
            val node = nodes.item(index)
            node.attributes.getNamedItem("name").nodeValue to node.textContent
        }
    }
    @Test fun polishAndEnglishHaveTheSameKeysAndFormattingArguments() {
        val english = strings("values"); val polish = strings("values-pl")
        assertEquals(english.keys,polish.keys)
        val placeholders = Regex("%[1-9][0-9]*\\$[sd]")
        for (key in english.keys) {
            assertTrue(polish.getValue(key).isNotBlank())
            assertEquals(key,placeholders.findAll(english.getValue(key)).map { it.value }.toList(),
                placeholders.findAll(polish.getValue(key)).map { it.value }.toList())
        }
    }
    @Test fun localeSwitchKeepsPageIdentityAndFormatsHostAndSpokenDigits() {
        val page = "settings"
        assertEquals(R.string.nav_settings,pageLabel(page))
        val en = strings("values"); val pl = strings("values-pl")
        assertNotEquals(en.getValue("nav_settings"),pl.getValue("nav_settings"))
        assertEquals(R.string.nav_settings,pageLabel(page))
        assertEquals("Host: https://host.invalid",String.format(Locale.ENGLISH,en.getValue("host_value"),"https://host.invalid"))
        assertEquals("Kod porównawczy: 0 1 2 3 4 5",String.format(Locale.forLanguageTag("pl"),pl.getValue("sas_value"),"0 1 2 3 4 5"))
        val message = UiMessage(R.string.host_value,listOf("https://host.invalid"))
        assertEquals(listOf("https://host.invalid"),message.arguments) // no pre-rendered English retained
    }
    private fun connectedUi() = MissionUi(enrolled=true,connection="SIGNED_SESSION",pairingState="CONNECTED",
        freshness=Freshness().accept(0,2000,now=1000),
        pairing=PairingRecord(TrustedHost("https://host.invalid","pin","spki","source","capsule","scope"),
            "request","digest",3000,true,true))

    @Test fun homeKeepsSavedPairingHistorySeparateFromCurrentVerifiedConnection() {
        val connected=connectedUi()
        assertEquals(R.string.state_connected,connected.connectionLabel(1000))
        assertEquals(R.string.state_pairing_saved,connected.pairingLabel())
        assertEquals(R.string.refresh_connection,connected.reconnectLabel(1000))
        // Crossing the signed deadline alone must downgrade the connection,
        // even before the ViewModel's scheduled expiry callback runs.
        assertEquals(R.string.state_stale,connected.connectionLabel(2000))
        assertEquals(R.string.state_pairing_saved,connected.pairingLabel())
        assertEquals(R.string.recover_session,connected.reconnectLabel(2000))
    }
    @Test fun homeAfterBackgroundTransportFailureOrSessionRejectionNeverClaimsCurrentConnection() {
        val connected=connectedUi()
        val background=connected.copy(connection="STALE",freshness=connected.freshness.invalidate("STALE"))
        val transportFailure=connected.copy(connection="OFFLINE_OR_DENIED",freshness=connected.freshness.invalidate("UNKNOWN"))
        val rejected=connected.sessionUnavailable().copy(connection="FRESH_ENROLLMENT_REQUIRED",
            freshness=connected.freshness.invalidate("UNKNOWN"))
        for ((ui,expected) in listOf(background to R.string.state_stale,transportFailure to R.string.state_unknown,
                rejected to R.string.state_recovery)) {
            assertEquals(expected,ui.connectionLabel(1000))
            assertEquals(R.string.state_pairing_saved,ui.pairingLabel())
            assertEquals(R.string.recover_session,ui.reconnectLabel(1000))
            assertEquals(connected.pairing,ui.pairing) // public trust retained for explicit recovery
        }
        // Enrollment rejection wins even if a stale positive observation remains.
        assertEquals(R.string.state_recovery,connected.sessionUnavailable().connectionLabel(1000))
        assertEquals(R.string.recover_session,connected.sessionUnavailable().reconnectLabel(1000))
    }

    @Test fun historicalSignedTimeNeverMakesStaleOrRevokedSessionCurrent() {
        assertNull(MissionUi().lastSignedResponseAt)
        val observed = connectedUi().copy(lastSignedResponseAt=1700000000)
        assertEquals("2023-11-14 22:13:20 UTC",formatSignedHostTime(observed.lastSignedResponseAt!!))
        val stale = observed.copy(freshness=observed.freshness.invalidate("STALE"))
        val revoked = observed.sessionUnavailable().copy(connection="FRESH_ENROLLMENT_REQUIRED",pairingState="REVOKED")
        assertEquals(observed.lastSignedResponseAt,stale.lastSignedResponseAt)
        assertEquals(R.string.state_stale,stale.connectionLabel(1000))
        assertEquals(observed.lastSignedResponseAt,revoked.lastSignedResponseAt)
        assertEquals(R.string.state_recovery,revoked.connectionLabel(1000))
    }
    @Test fun disabledReasonsTrackBusyMissingPendingExpiredAndRevokedWithoutGrantingPermissions() {
        val initial = MissionUi()
        assertNull(initial.primaryDisabledReason(PrimaryAction.CONNECT,1000))
        assertEquals(R.string.reason_no_pairing,initial.primaryDisabledReason(PrimaryAction.RECONNECT,1000))
        assertEquals(R.string.reason_no_session,initial.primaryDisabledReason(PrimaryAction.STATUS,1000))
        val waiting = connectedUi().copy(enrolled=false,pairingState="PENDING",
            pairing=connectedUi().pairing!!.copy(trusted=false,completeAttempted=false))
        assertEquals(R.string.reason_pairing_pending,waiting.primaryDisabledReason(PrimaryAction.RECONNECT,1000))
        assertNull(waiting.primaryDisabledReason(PrimaryAction.PAIRING_STATUS,1000))
        assertEquals(R.string.reason_expired,waiting.primaryDisabledReason(PrimaryAction.PAIRING_STATUS,3000))
        assertEquals(R.string.reason_expired,waiting.primaryDisabledReason(PrimaryAction.RECONNECT,3000))
        assertEquals(R.string.reason_revoked,waiting.copy(pairingState="REVOKED").primaryDisabledReason(PrimaryAction.RECONNECT,1000))
        for (action in PrimaryAction.values()) {
            assertEquals(action.name,R.string.reason_busy,waiting.copy(busy=true).primaryDisabledReason(action,1000))
        }
        // Durable approval can reconnect after invite expiry; an expired observation can request fresh status.
        assertNull(connectedUi().primaryDisabledReason(PrimaryAction.RECONNECT,4000))
        assertNull(connectedUi().copy(freshness=Freshness()).primaryDisabledReason(PrimaryAction.STATUS,4000))
        assertEquals(R.string.reason_already_connected,connectedUi().primaryDisabledReason(PrimaryAction.PAIRING_STATUS,1000))
    }

}
