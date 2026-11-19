"""Synthetic literals only; no actual provider or browser key is read."""
import json
import unittest

from runtime import secret_redaction as api


class ProviderKeyFamilyTests(unittest.TestCase):
    def key(self, character='A', count=35):
        return 'AIza' + character * count

    def test_bare_provider_key_shape_is_sensitive(self):
        self.assertTrue(api.contains_sensitive_material(self.key()), 'Key shape was not detected')

    def test_unicode_neighbors_do_not_hide_the_key_shape(self):
        value = 'Ł' + self.key('B') + 'ą'
        self.assertTrue(api.contains_sensitive_material(value), 'Unicode adjacency hid the key shape')
        self.assertTrue(api.redact_sensitive_text(value) == 'Ł[REDACTED]ą', 'Unicode-adjacent key survived')

    def test_redaction_retains_no_key_bytes_or_tail(self):
        value = self.key('C', 70)
        self.assertTrue(api.redact_sensitive_text(value) == api.REDACTION_MARKER, 'Key bytes survived redaction')

    def test_structured_data_uses_the_same_shared_detection(self):
        self.assertTrue(api.contains_sensitive_material({'value': self.key('D')}), 'Structured key shape survived')

    def test_all_occurrences_are_replaced(self):
        value = 'before ' + self.key('E') + ' and ' + self.key('F') + ' after'
        expected = 'before [REDACTED] and [REDACTED] after'
        self.assertTrue(api.redact_sensitive_text(value) == expected, 'At least one occurrence survived')

    def test_short_non_key_text_and_plain_text_are_preserved(self):
        for value in ('', 'plain diagnostic', self.key('G', 34)):
            with self.subTest(length=len(value)):
                self.assertFalse(api.contains_sensitive_material(value), 'Non-key text was classified as a key')
                self.assertTrue(api.redact_sensitive_text(value) == value, 'Non-key text was changed')

    def test_existing_provider_families_keep_their_policy(self):
        for value in ('sk-' + 'Z' * 16, 'AKIA' + 'Z' * 16, 'ghp_' + 'Z' * 16):
            with self.subTest(length=len(value)):
                self.assertTrue(api.contains_sensitive_material(value), 'Existing family was missed')
                self.assertTrue(api.redact_sensitive_text(value) == api.REDACTION_MARKER, 'Existing family was weakened')

    def test_malformed_inputs_remain_fail_closed(self):
        self.assertTrue(api.contains_sensitive_material(object()))
        with self.assertRaises(TypeError):
            api.redact_sensitive_text(None)

    def test_google_fragments_inside_old_github_families_are_fully_redacted(self):
        values = (
            'ghs_' + self.key('H') + '.' + 'P' * 12 + '.' + 'S' * 12,
            'ghs_' + 'H' * 12 + '.' + self.key('P') + '.' + 'S' * 12,
            'ghs_' + 'H' * 12 + '.' + 'P' * 12 + '.' + self.key('S'),
            'ghp_' + self.key('J'),
            'github_pat_' + self.key('K'),
        )
        for index, value in enumerate(values):
            with self.subTest(case=index):
                self.assertTrue(api.redact_sensitive_text(value) == api.REDACTION_MARKER,
                                'An overlapping old-family credential was only partially redacted')

    def test_old_github_fragments_inside_google_shapes_leave_no_prefix(self):
        for prefix in ('ghp_', 'github_pat_'):
            value = 'AIza' + 'A' * 5 + prefix + 'B' * 35
            with self.subTest(family=prefix):
                self.assertTrue(api.redact_sensitive_text(value) == api.REDACTION_MARKER,
                                'An overlapping Google-family credential retained a prefix')


    def test_opaque_credential_fields_are_detected_in_nested_json(self):
        payload = {"observations": [{"api_key": "opaque synthetic fixture"}]}
        self.assertTrue(api.contains_sensitive_material(payload))
        self.assertTrue(api.contains_sensitive_material(json.dumps(payload)))

    def test_redaction_preserves_json_around_nested_credential_values(self):
        payload = {
            "observations": [
                {"Password": 'synthetic "value"'},
                {"token": "synthetic" + chr(92) + "fixture"},
            ],
            "summary": "healthy fixture",
        }
        redacted = api.redact_sensitive_text(json.dumps(payload))
        self.assertEqual(json.loads(redacted), {
            "observations": [{"Password": api.REDACTION_MARKER}, {"token": api.REDACTION_MARKER}],
            "summary": "healthy fixture",
        })

    def test_missing_value_and_unrelated_json_fields_are_preserved(self):
        rendered = json.dumps({"token": "n/a", "token_budget": "1000", "summary": "healthy fixture"})
        self.assertFalse(api.contains_sensitive_material(rendered))
        self.assertEqual(api.redact_sensitive_text(rendered), rendered)
