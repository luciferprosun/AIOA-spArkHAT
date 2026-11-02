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
}
