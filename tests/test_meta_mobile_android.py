"""Android SOURCE checks only; never counted as a compiled JVM/device test."""
import hashlib
import json
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
ANDROID=ROOT/'clients/android'
SRC=ANDROID/'app/src/main/java/eu/sparkhat/aioa/companion'
NS='{http://schemas.android.com/apk/res/android}'


class AndroidSourceTests(unittest.TestCase):
    def test_package_revision_and_pinned_build_inputs(self):
        build=(ANDROID/'app/build.gradle.kts').read_text()
        for value in ['eu.sparkhat.aioa.companion','compileSdk = 36','minSdk = 26','targetSdk = 36',
                      'versionCode = 2','jvmToolchain(17)']:self.assertIn(value,build)
        props=(ANDROID/'gradle/wrapper/gradle-wrapper.properties').read_text()
        self.assertIn('gradle-8.13-bin.zip',props)
        self.assertIn('20f1b1176237254a6fc204d8434196fa11a4cfb387567519c61556e8710aed78',props)

    def test_manifest_is_private_no_backup_and_no_cleartext(self):
        root=ET.parse(ANDROID/'app/src/main/AndroidManifest.xml').getroot();app=root.find('application')
        self.assertEqual('false',app.attrib[NS+'allowBackup']);self.assertEqual('false',app.attrib[NS+'usesCleartextTraffic'])
        self.assertEqual('false',app.attrib[NS+'fullBackupContent'])
        self.assertEqual({'android.permission.INTERNET'}, {p.attrib[NS+'name'] for p in root.findall('uses-permission')})
        security=(ANDROID/'app/src/main/res/xml/network_security_config.xml').read_text()
        self.assertIn('src="system"',security);self.assertNotIn('src="user"',security)

    def test_android_keystore_p256_only_and_session_not_persisted(self):
        identity=(SRC/'TransportIdentity.kt').read_text()
        for value in ['AndroidKeyStore','secp256r1','SHA256withECDSA','KeyProperties.PURPOSE_SIGN']:
            self.assertIn(value,identity)
        all_source='\n'.join(p.read_text() for p in SRC.glob('*.kt'))
        for forbidden in ['setAcceptThirdPartyCookies','TrustAll','trustAll','Ed25519','MODEL_API_KEY',
                          'meta_api_key','operator_approved=True','.putString("token"', 'retryOnConnectionFailure(true)']:
            self.assertNotIn(forbidden,all_source)

    def test_tls_pins_no_redirects_no_automatic_post_retry(self):
        source=(SRC/'MobileClient.kt').read_text()
        for value in ['TlsVersion.TLS_1_3','CertificatePinner','retryOnConnectionFailure(false)',
                      'followRedirects(false)','followSslRedirects(false)','verifyHostProof','verifyObservation',
                      'REMOTE_DEPLOYMENT_BLOCKED','OFFLINE_FIXTURE']:
            self.assertIn(value,source)
        self.assertNotIn('hostnameVerifier(',source);self.assertNotIn('sslSocketFactory(',source)

    def test_one_contract_matches_android_constants_and_vector(self):
        contract=json.loads((ROOT/'protocol/mobile_mission_v1.json').read_text())
        source=(SRC/'Wire.kt').read_text()
        self.assertIn(contract['base_path'],source)
        for name in ['host_proof_schema','request_proof_schema','enrollment_proof_schema','observation_schema']:
            self.assertIn(contract[name],source)
        vector=json.loads((ROOT/'tests/fixtures/mobile_wire_vector.json').read_text())
        from runtime.mobile_gateway import wire
        wire.verify(vector['spki'],vector['signature'],vector['proof'])
        self.assertEqual(vector['canonical_sha256'],wire.digest(wire.canonical(vector['proof'])))

    def test_scroll_lifecycle_unknown_and_no_approval_button(self):
        ui=(SRC/'MainActivity.kt').read_text();vm=(SRC/'MissionViewModel.kt').read_text()
        for value in ['verticalScroll','imePadding','Connection','Pairing','Last Receipt','Billing Unverified',
                      'Not yet available','Evidence','STOP']:self.assertIn(value,ui)
        for value in ['STALE','UNKNOWN','generation','readback','background','pending_proposal']:
            self.assertIn(value,vm)
        self.assertNotIn('fun run(', (SRC/'MobileClient.kt').read_text())
        self.assertNotIn('fun approve(', (SRC/'MobileClient.kt').read_text())

    def test_wrapper_binary_is_known_upstream_not_unlicensed_project_code(self):
        p=ANDROID/'gradle/wrapper/gradle-wrapper.jar'
        self.assertEqual('81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f',hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertIn('Apache License',(ANDROID/'licenses/gradle-wrapper-LICENSE.txt').read_text())
        self.assertIn('neutral',(ANDROID/'NOTICE.md').read_text().lower())


if __name__=='__main__':unittest.main()
