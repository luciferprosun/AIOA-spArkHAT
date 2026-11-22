"""F01 keeps caller evidence labels on a read-only recommendation boundary."""

from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from q09_support import Fixture
from runtime.core_admission import AdmissionError, Capability
from runtime.tools.task_continuation import (
    MANIFEST_SCHEMA,
    build_resume_summary,
    select_next_local_task,
)


class ContinuationEvidenceBoundaryTests(unittest.TestCase):
    base = 'a' * 40

    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        self.store = self.root / 'core.json'
        self.core = Fixture(self.store)
        self.addCleanup(self.core.close)
        self.core.init()

    def manifest(self, refs):
        return {
            'schema': MANIFEST_SCHEMA,
            'base_sha': self.base,
            'tasks': [
                {'task_id': 'collect', 'status': 'DONE', 'dependencies': [],
                 'evidence_refs': refs, 'scope': 'LOCAL_OFFLINE'},
                {'task_id': 'check', 'status': 'READY', 'dependencies': ['collect'],
                 'evidence_refs': [], 'scope': 'LOCAL_OFFLINE'},
            ],
        }

    def test_unverified_labels_grant_no_io_or_core_authority(self):
        tampered = self.root / 'evidence.json'
        digest = sha256(b'original fixture bytes').hexdigest()
        tampered.write_bytes(b'altered fixture bytes')
        before = self.store.read_bytes()
        attempted_io = (
            'builtins.open', 'io.open', 'os.open', 'os.system',
            'socket.socket', 'socket.create_connection', 'subprocess.Popen',
        )
        labels = (str(self.root / 'missing.json'), f'{tampered}#sha256={digest}',
                  '../outside/evidence.json', 'https://example.invalid/evidence#sha256=invalid')
        for label in labels:
            with self.subTest(label=label):
                manifest = self.manifest([label])
                with ExitStack() as denial:
                    for target in attempted_io:
                        denial.enter_context(patch(target, side_effect=AssertionError(target)))
                    selected = select_next_local_task(manifest, expected_base_sha=self.base)
                    summary = json.loads(build_resume_summary(
                        manifest, selected, expected_base_sha=self.base))
                self.assertEqual(selected['task_id'], 'check')
                self.assertEqual(selected['status'], 'NEXT')
                self.assertEqual(selected['effect_authority'], 'NONE')
                self.assertEqual(summary['effect_authority'], 'NONE')
                self.assertEqual(summary['tasks'][0]['evidence_refs'], [label])
                for claimant in (selected, summary, self.core.p(Capability.READ)):
                    with self.assertRaisesRegex(AdmissionError, 'CORE_ADMISSION_DENIED'):
                        self.core.core.require(claimant, Capability.COMMIT)
                self.assertEqual(self.store.read_bytes(), before)

    def test_stale_or_untrusted_base_and_forged_summary_are_denied(self):
        manifest = self.manifest(['fixture/ref'])
        selected = select_next_local_task(manifest, expected_base_sha=self.base)
        for trusted_base in ('b' * 40, 'invalid'):
            with self.subTest(base=trusted_base), self.assertRaises(ValueError):
                select_next_local_task(manifest, expected_base_sha=trusted_base)
            with self.subTest(summary_base=trusted_base), self.assertRaises(ValueError):
                build_resume_summary(manifest, selected, expected_base_sha=trusted_base)
        with self.assertRaisesRegex(ValueError, 'selection does not match'):
            build_resume_summary(
                manifest, dict(selected, effect_authority='COMMIT'), expected_base_sha=self.base,
            )
