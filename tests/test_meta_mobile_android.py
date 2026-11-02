"""Android SOURCE checks only; never counted as a compiled JVM/device test."""
import hashlib
import json
from pathlib import Path
import re
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
                      'versionCode = 3','jvmToolchain(17)']:self.assertIn(value,build)
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
        resource=ANDROID/'app/src/test/resources/mobile_wire_vector.json'
        self.assertEqual(vector,json.loads(resource.read_text()))
        self.assertNotIn('resources.srcDir("../../../tests/fixtures")',(ANDROID/'app/build.gradle.kts').read_text())
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

    def test_reenrollment_is_available_and_known_session_loss_is_distinct(self):
        ui=(SRC/'MainActivity.kt').read_text();vm=(SRC/'MissionViewModel.kt').read_text()
        self.assertNotIn('!ui.enrolled && code.isNotEmpty()',ui)
        self.assertIn('SessionUnavailable',vm)
        self.assertIn('sessionUnavailable()',vm)

    def test_foreground_freshness_has_signed_deadline_and_expiry_invalidation(self):
        client=(SRC/'MobileClient.kt').read_text();vm=(SRC/'MissionViewModel.kt').read_text()
        self.assertIn('validUntilElapsedMs',client)
        self.assertIn('validUntilElapsedMs',vm)
        self.assertIn('delay(',vm)
        self.assertIn('isFresh()',vm)

    def test_pending_can_only_be_archived_explicitly_without_faking_core_resolution(self):
        ui=(SRC/'MainActivity.kt').read_text();vm=(SRC/'MissionViewModel.kt').read_text()
        self.assertIn('AlertDialog(',ui)
        self.assertIn('archivePendingHint()',vm)
        self.assertIn('unresolved_proposals',vm)
        self.assertIn('Core UNKNOWN stays UNKNOWN',ui)

    def test_agent_pending_handoff_is_persisted_before_unblocking_and_sends_no_request(self):
        vm=(SRC/'MissionViewModel.kt').read_text()
        match=re.search(r'fun archivePendingAgentHint\(\) \{(.*?)(?=\n    (?:private )?fun |\n    override fun )',vm,re.S)
        self.assertIsNotNone(match,'v2 must offer an explicit local handoff after session loss')
        body=match.group(1)
        self.assertIn('if (ui.busy) return',body)
        self.assertIn('PendingHints.archive(proposal,ui.archivedAgents)',body)
        self.assertRegex(body,r'if \(prefs\.edit\(\)\.putStringSet\("unresolved_agent_proposals",history\.toSet\(\)\)\s*'
            r'\.remove\("pending_agent_proposal"\)\.commit\(\)\) \{\s*ui = ui\.copy\(pendingAgent=null,archivedAgents=history,')
        self.assertEqual(1,body.count('pendingAgent=null'))
        self.assertNotIn('.apply()',body)
        for forbidden in ('client.','request(','run_agent','reconcile','approve(','.stop('):
            self.assertNotIn(forbidden,body)
        self.assertIn('Core UNKNOWN is unchanged',body)

    def test_agent_handoff_survives_ui_restart_and_session_revocation(self):
        vm=(SRC/'MissionViewModel.kt').read_text()
        self.assertIn('val archivedAgents: List<String> = emptyList()',vm)
        self.assertIn('archivedAgents=prefs.getStringSet("unresolved_agent_proposals",emptySet())',vm)
        revoke=vm.split('fun revoke()',1)[1].split('fun agentStatus()',1)[0]
        self.assertIn('pendingAgent=ui.pendingAgent,archivedAgents=ui.archivedAgents',revoke)
        self.assertLess(vm.index('putString("pending_agent_proposal",proposal).commit()'),
                        vm.index('client.agentProposal('))

    def test_agent_handoff_requires_explicit_confirmation_and_displays_retained_ids(self):
        ui=(SRC/'MainActivity.kt').read_text()
        self.assertIn('if (archiveAgentDialog && ui.pendingAgent != null) AlertDialog(',ui)
        self.assertIn('model.archivePendingAgentHint(); archiveAgentDialog=false',ui)
        self.assertIn('enabled=!ui.busy && ui.pendingAgent!=null,onClick={ archiveAgentDialog=true }',ui)
        self.assertIn('ui.archivedAgents.joinToString("\\n")',ui)
        self.assertIn('Core UNKNOWN stays UNKNOWN',ui)


if __name__=='__main__':unittest.main()
