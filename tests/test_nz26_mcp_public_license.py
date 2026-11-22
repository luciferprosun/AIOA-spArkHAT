"""Regression coverage for the Core MCP public LICENSE projection."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from runtime.core_admission import Capability
from runtime.mcp_bridge.adapter import CoreMissionMCPAdapter, build_task
from runtime.mcp_bridge.contracts import ContractError
from runtime.mcp_bridge.read_ops import bounded_public_license
from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition


class MCPPublicLicenseTests(unittest.TestCase):
    def test_byte_limit_preserves_complete_utf8_characters_and_receipt(self):
        text = 'ą€🙂\nPublic notice\n'
        raw = text.encode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'LICENSE').write_bytes(raw)
            source = ('1' * 40, 'a' * 64)
            host = OfflineMetaComposition(root / 'state', source_probe=lambda: source)
            try:
                reader = host.core.local_operator(Capability.READ)
                bridge = CoreMissionMCPAdapter(host.missions, reader, project_root=root)
                for maximum, expected in ((1, ''), (2, 'ą'), (4, 'ą'), (8, 'ą€'),
                                          (9, 'ą€🙂'), (len(raw), text)):
                    with self.subTest(maximum=maximum):
                        task = build_task('fs.read', {'path': 'LICENSE', 'bytes': maximum},
                                          target_project='aioa', source='mcp_fixture')
                        try:
                            result = bridge.submit(task, source_sha=source[0], capsule_digest=source[1])
                        except UnicodeDecodeError:
                            self.fail('A valid UTF-8 LICENSE must survive a byte limit inside a character')
                        self.assertEqual(result['state'], 'MCP_LINKED')
                        self.assertFalse(result['can_authorize_effects'])
                        self.assertIsNone(result['mission'])
                        self.assertEqual(result['read'], {
                            'path': 'LICENSE',
                            'text': expected,
                            'sha256': digest,
                            'bytes': len(raw),
                            'truncated': maximum < len(raw),
                            'local_readback_verified': True,
                            'live_verified': False,
                            'authority': 'NONE',
                        })
                        self.assertLessEqual(len(result['read']['text'].encode('utf-8')), maximum)
                        self.assertEqual(bridge.result(task.task_id), result)
            finally:
                host.close()

    def test_invalid_utf8_is_denied_even_beyond_the_excerpt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'LICENSE').write_bytes(b'public\xff')
            with self.assertRaises(ValueError) as raised:
                bounded_public_license(root, maximum=3)
        self.assertIsInstance(raised.exception, ContractError)
