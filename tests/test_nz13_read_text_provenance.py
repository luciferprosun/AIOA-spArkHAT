"""Bounded summaries disclose truncation/redaction and retain source digests."""
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from test_nz13_github_contexts import RichContextFixture

from runtime.mcp_bridge import native_read as api


class ReadTextProvenanceTests(unittest.TestCase):
    def read(self, fixture, operation='github.issue_contexts'):
        with patch.object(api, '_github_json', side_effect=fixture.get):
            result = api.read(operation, '.')
        return result['data']

    def metadata(self, item):
        self.assertIn('text_provenance', item, 'Missing per-field summary provenance')
        return item['text_provenance']

    def check_field(self, item, field, source, maximum):
        meta = self.metadata(item)[field]
        raw = (source or '').encode()
        self.assertEqual({'source_bytes', 'source_sha256', 'redacted', 'truncated', 'null'}, set(meta))
        self.assertEqual(len(raw), meta['source_bytes'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), meta['source_sha256'])
        self.assertEqual(source is None, meta['null'])
        self.assertLessEqual(len(item[field].encode()), maximum)
        return meta

    def test_long_issue_title_and_body_record_exact_original_byte_digests(self):
        fixture = RichContextFixture()
        row = fixture.responses[fixture.page_endpoint('issues', 1)][0]
        row.update(title='T' * 300, body='B' * 1000)
        item = self.read(fixture)['items'][0]
        for field, maximum in [('title', 256), ('body', 768)]:
            with self.subTest(field=field):
                meta = self.check_field(item, field, row[field], maximum)
                self.assertTrue(meta['truncated'])
                self.assertFalse(meta['redacted'])
                self.assertEqual(maximum, len(item[field].encode()))

    def test_null_body_is_distinct_from_an_empty_body(self):
        for source in (None, ''):
            with self.subTest(null=source is None):
                fixture = RichContextFixture()
                fixture.responses[fixture.page_endpoint('issues', 1)][0]['body'] = source
                item = self.read(fixture)['items'][0]
                meta = self.check_field(item, 'body', source, 768)
                self.assertEqual('', item['body'])
                self.assertFalse(meta['truncated'])
                self.assertFalse(meta['redacted'])

    def test_utf8_cut_uses_byte_limit_and_reports_omission(self):
        fixture = RichContextFixture()
        row = fixture.responses[fixture.page_endpoint('issues', 1)][0]
        row['title'] = 'x' * 255 + '\U0001f680'
        item = self.read(fixture)['items'][0]
        self.assertTrue(self.check_field(item, 'title', row['title'], 256)['truncated'])
        self.assertEqual('x' * 255, item['title'])

    def test_redaction_is_full_suppression_separate_from_truncation(self):
        fixture = RichContextFixture()
        synthetic = 'ghp_' + 'SYNTHETIC' * 5
        source = 'Neutral before ' + synthetic + ' neutral after ' + 'z' * 900
        fixture.responses[fixture.page_endpoint('issues', 1)][0]['body'] = source
        data = self.read(fixture)
        item = data['items'][0]
        meta = self.check_field(item, 'body', source, 768)
        self.assertTrue(meta['redacted'])
        self.assertFalse(meta['truncated'])
        self.assertEqual('[REDACTED]', item['body'])
        self.assertTrue(synthetic not in json.dumps(data), 'Synthetic full field escaped')

    def test_labels_and_author_have_independent_text_provenance(self):
        fixture = RichContextFixture()
        row = fixture.responses[fixture.page_endpoint('issues', 1)][0]
        row['labels'][0]['name'] = 'label' * 20
        row['user']['login'] = 'author' * 20
        item = self.read(fixture)['items'][0]
        meta = self.metadata(item)
        self.assertEqual({'title', 'body', 'labels', 'author'}, set(meta))
        label = meta['labels'][0]
        self.assertTrue(label['truncated'])
        self.assertEqual(100, label['source_bytes'])
        self.assertEqual(hashlib.sha256(row['labels'][0]['name'].encode()).hexdigest(), label['source_sha256'])
        self.assertTrue(self.check_field(item, 'author', row['user']['login'], 64)['truncated'])

    def test_pr_and_action_metadata_share_the_same_read_plane(self):
        fixture = RichContextFixture()
        for operation, kind, field, number in [('github.pull_requests', 'pulls', 'body', 2),
                                                ('github.actions', 'actions/runs', 'name', 3)]:
            with self.subTest(operation=operation):
                value = fixture.responses[fixture.page_endpoint(kind, 1)]
                row = value['workflow_runs'][0] if kind == 'actions/runs' else value[0]
                row[field] = 'n' * 1200
                data = self.read(fixture, operation)
                self.assertEqual('aioa.github-read-context.v2', data['schema'])
                item = data['items'][0]
                self.assertTrue(self.metadata(item)[field]['truncated'])
                self.assertEqual('NONE', data['authority'])
                self.assertEqual('REMOTE_UNTRUSTED_DATA', item['taint'])
                self.assertEqual(number, item.get('number', item.get('run_id')))

    def test_current_schema_requires_provenance_while_historical_v1_stays_readable(self):
        data = self.read(RichContextFixture())
        self.assertEqual('aioa.github-read-context.v2', data['schema'])
        api.validate_context_data('github.issue_contexts', data)
        missing = copy.deepcopy(data)
        missing['items'][0].pop('text_provenance')
        with self.assertRaises(ValueError):
            api.validate_context_data('github.issue_contexts', missing)
        legacy = copy.deepcopy(missing)
        legacy['schema'] = 'aioa.github-read-context.v1'
        api.validate_context_data('github.issue_contexts', legacy)
        mixed = copy.deepcopy(data)
        mixed['schema'] = 'aioa.github-read-context.v1'
        with self.assertRaises(ValueError):
            api.validate_context_data('github.issue_contexts', mixed)

    def test_forged_metadata_is_rejected_before_context_acceptance(self):
        data = self.read(RichContextFixture())
        self.metadata(data['items'][0])
        mutations = [('source_bytes', True), ('source_bytes', -1), ('source_bytes', 32769),
                     ('source_sha256', '0' * 64), ('redacted', 1), ('redacted', True),
                     ('truncated', True), ('null', True), ('extra', 'unknown')]
        for field, value in mutations:
            with self.subTest(field=field, type=type(value).__name__):
                changed = copy.deepcopy(data)
                changed['items'][0]['text_provenance']['body'][field] = value
                with self.assertRaises(ValueError):
                    api.validate_context_data('github.issue_contexts', changed)

    def test_metadata_field_inventory_is_exact(self):
        data = self.read(RichContextFixture())
        self.metadata(data['items'][0])
        for mutation in ('drop_author', 'extra_label', 'wrong_type', 'extra_field'):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(data)
                meta = changed['items'][0]['text_provenance']
                if mutation == 'drop_author':
                    del meta['author']
                elif mutation == 'extra_label':
                    meta['labels'].append(copy.deepcopy(meta['labels'][0]))
                elif mutation == 'wrong_type':
                    meta['labels'] = {}
                else:
                    meta['unrecognized'] = {}
                with self.assertRaises(ValueError):
                    api.validate_context_data('github.issue_contexts', changed)

    def test_inventory_digest_pins_the_new_output_schema(self):
        inventory = api.context_inventory()
        self.assertEqual('aioa.native-github-read-inventory.v2', inventory['schema'])
        for item in inventory['tools']:
            schema = {'operation': item['name'], 'arguments': {}, 'repository': api.REPOSITORY,
                      'repository_id': api.REPOSITORY_ID, 'per_page': 10, 'page_limit': 2,
                      'output_schema': 'aioa.github-read-context.v2',
                      'text_provenance': 'SOURCE_UTF8_BYTES_SHA256_REDACTION_TRUNCATION_V1'}
            expected = hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            self.assertEqual(expected, item['schema_sha256'])
