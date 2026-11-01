"""Portable compatibility boundary for v1 and local-zero sessions."""
import unittest
from runtime.core_admission import OwnerScope
from runtime.mission.tools import SessionGrant,LocalSessionGrant

class LegacySessionBoundaryTests(unittest.TestCase):
    def test_git_capability_is_additive_zero_profile_only_not_legacy_v1(self):
        fields=dict(session_id='session',scope=OwnerScope('t','o','s','i'),workspace='workspace',
            policy_revision=2,capabilities=('GIT_COMMIT',),completion_digest='a'*64,
            issued_at=1,expires_at=100,epoch=1,risk_units=1,deadline_seconds=20,output_bytes=8192)
        with self.assertRaises(ValueError):SessionGrant(**fields,money_nano=1)
        self.assertEqual(0,LocalSessionGrant(**fields,money_nano=0).money_nano)


if __name__=='__main__':unittest.main()
