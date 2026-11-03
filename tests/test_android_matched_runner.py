"""Known publisher rollout; strict/v1 remain unchanged, unknown metadata denied."""
import hashlib,json,unittest
from unittest.mock import patch
from tests.test_android_image_metadata import ImageMetadataConsistencyTests
from tests.test_android_postmerge_ci import context,SHA
from scripts.android import ci_build as ci

PROFILE='DEBUG_UBUNTU22_V2';IMAGE='20261101.347.1';PIN='29096352b00e4ed83a17ca7c04e54650ea3197842d07e95901ff1a82a21817b3'
IMAGE_SET='20261026.341.1|20261101.347.1'

class MatchedRunnerTests(unittest.TestCase):
    def raw(self):return ImageMetadataConsistencyTests().raw(IMAGE).replace(b'ubuntu-24.04',b'ubuntu-22.04')
    def env(self):return {**context(),'AIOA_BUILD_PROFILE':PROFILE,'AIOA_DEBUG_ENVIRONMENT_ACK':'true',
        'ImageVersion':IMAGE,'ImageOS':'ubuntu22','AIOA_CODEQL_REQUESTED':'false','AIOA_APPROVED_RUNNER_IMAGES':IMAGE_SET,'AIOA_IMAGE_SNAPSHOT':json.dumps({
            'build_profile':PROFILE,'metadata_version':IMAGE,'declared_version':IMAGE,'metadata_sha256':PIN,'image_identity_status':'MATCHED'})}
    def test_bootstrap_requires_matching_published_pair_and_exact_observed_metadata_pin(self):
        ns,_=ImageMetadataConsistencyTests().bootstrap()
        original=hashlib.sha256
        # Synthetic raw is not the actual runner bytes. Pin is tested separately;
        # only the byte hash is substituted to exercise all parser decisions.
        class Hash:
            def hexdigest(self):return PIN
        with patch.object(ns['hashlib'],'sha256',return_value=Hash()):
            value=ns['check_image'](self.raw(),self.env());self.assertEqual('MATCHED',value['image_identity_status'])
            for raw,env in ((self.raw().replace(IMAGE.encode(),b'20261102.999.1'),self.env()),
                (self.raw(),{**self.env(),'ImageVersion':'20261102.999.1'}),(self.raw(),{**self.env(),'AIOA_BUILD_PROFILE':'STRICT'})):
                with self.assertRaises(SystemExit):ns['check_image'](raw,env)
        with self.assertRaises(SystemExit):ns['check_image'](self.raw(),self.env())
    def test_context_rejects_wrong_hash_mismatch_codeql_or_sdk_drift(self):
        env=self.env();ci.context_check(env,SHA,IMAGE)
        for key,value in (('metadata_sha256','0'*64),('image_identity_status','MISMATCH_ACCEPTED_DEBUG'),('metadata_version','20261025.340.1')):
            snapshot=json.loads(env['AIOA_IMAGE_SNAPSHOT']);snapshot[key]=value
            with self.assertRaises(ci.lib.Blocked):ci.context_check({**env,'AIOA_IMAGE_SNAPSHOT':json.dumps(snapshot)},SHA,IMAGE)
        with self.assertRaises(ci.lib.Blocked):ci.context_check(env,SHA,IMAGE,purpose='codeql')
        with patch.object(ci.lib,'source_check',return_value={}),patch.object(ci,'workflow_check'),patch.object(ci,'branch_head_check'),patch.object(ci,'sdk_inventory',return_value={'inventory_sha256':'0'*64}):
            with self.assertRaises(ci.lib.Blocked):ci.preflight({**env,'ANDROID_SDK_ROOT':'/usr/local/lib/android/sdk'},SHA,IMAGE)

    def test_known_approved_legacy_tuple_in_rolling_pool_is_explicit_not_forged_match(self):
        legacy={'build_profile':PROFILE,'declared_version':'20261026.341.1','metadata_version':'20261025.340.1',
            'metadata_sha256':'08a840f7186e0ab52ee613d5cafee66d245430928627dd25f6dc638bdd7e481f','image_identity_status':'MISMATCH_ACCEPTED_DEBUG'}
        env={**self.env(),'ImageVersion':'20261026.341.1','AIOA_IMAGE_SNAPSHOT':json.dumps(legacy)}
        ci.context_check(env,SHA,'20261026.341.1')
        self.assertEqual(legacy,ci.profile_evidence(env)['runner_observation'])
        with self.assertRaises(ci.lib.Blocked):ci.context_check({**env,'AIOA_APPROVED_RUNNER_IMAGES':'20261101.347.1'},SHA,'20261026.341.1')

if __name__=='__main__':unittest.main()
