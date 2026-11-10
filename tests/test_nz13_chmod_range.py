"""Regression coverage for advisory chmod modes and catalog input validation."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.tools import command_grammar
from runtime.tools.command_grammar import validate_command_shape


class ChmodOperatorRangeTests(unittest.TestCase):
    def test_nonoperator_characters_in_old_plus_to_equals_range_are_rejected(self):
        for operator in (',', '.', '/', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', ':'):
            with self.subTest(operator=operator):
                result = validate_command_shape('chmod u' + operator + 'r file.txt')
                self.assertEqual('suspicious', result['status'])
                self.assertIn('invalid_chmod_mode', result['reasons'])
                self.assertNotIn('valid_chmod_mode', result['reasons'])

    def test_literal_add_remove_assign_and_octal_modes_preserve_advisory_contract(self):
        for mode in ('u+r', 'g-w', 'a=rx', 'ug+rw', 'o-rwx', '0640', '755'):
            with self.subTest(mode=mode):
                result = validate_command_shape('chmod ' + mode + ' file.txt')
                self.assertEqual('chmod', result['base'])
                self.assertIn(result['status'], ('family', 'exact'))
                self.assertIn('valid_chmod_mode', result['reasons'])
                self.assertNotIn('execution_authorized', result)


class CommandPatternCatalogTests(unittest.TestCase):
    def test_non_list_catalog_is_rejected_as_a_type_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'command_patterns.json'
            for value in ({}, None, 'catalog', 42, True):
                with self.subTest(value=value):
                    path.write_text(json.dumps(value), encoding='utf-8')
                    with (patch.object(command_grammar, '_PATTERN_PATH', path),
                          self.assertRaises(TypeError)):
                        command_grammar.validate_command_shape('chmod 640 file.txt')

    def test_malformed_catalog_preserves_json_decode_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'command_patterns.json'
            path.write_text('{', encoding='utf-8')
            with (patch.object(command_grammar, '_PATTERN_PATH', path),
                  self.assertRaises(json.JSONDecodeError)):
                command_grammar.validate_command_shape('chmod 640 file.txt')

    def test_list_catalog_retains_unknown_base_advisory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'command_patterns.json'
            path.write_text('[]', encoding='utf-8')
            with patch.object(command_grammar, '_PATTERN_PATH', path):
                result = command_grammar.validate_command_shape('chmod 640 file.txt')
            self.assertEqual('suspicious', result['status'])
            self.assertEqual('unknown', result['danger'])
            self.assertEqual(['unknown_base'], result['reasons'])
            self.assertNotIn('execution_authorized', result)


if __name__ == '__main__':
    unittest.main()
