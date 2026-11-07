"""Adversarial source is data: validation must never import it into the reporter."""

import json
import tempfile
import unittest
import warnings
from pathlib import Path

import test_nz11_general_recipe as recipe_support

from runtime.mission import repository_worker


class ObservationPolicyTests(unittest.TestCase):
    def validate(self, files, module="textutil", function="slug"):
        program = getattr(repository_worker, "PythonJsonProgram", None)
        self.assertTrue(callable(program), "inert program validation is missing")
        archive = {
            "files": [
                {"path": path, "mode": 0o644, "text": text}
                for path, text in files.items()
            ]
        }
        program(
            archive,
            ["src"],
            [{"case_id": "spaces", "module": module, "function": function,
              "arguments": ["  One   TWO "]}],
        )

    def test_plain_json_function_is_admitted_as_inert_source(self):
        self.assertIsNone(self.validate({
            "src/textutil.py": 'def slug(text):\n    return "-".join(text.lower().split())\n',
        }))

    def test_local_helper_modules_are_admitted_without_import_execution(self):
        self.assertIsNone(self.validate({
            "src/textutil.py": "from helpers import normalize\ndef slug(text):\n    return normalize(text)\n",
            "src/helpers.py": "def normalize(value):\n    return value.strip().lower()\n",
        }))

    def test_ambient_interpreter_import_cannot_access_the_reporter(self):
        with self.assertRaises(ValueError):
            self.validate({"src/textutil.py":
                'import sys\ndef slug(text):\n    return sys.modules["__main__"]\n'})

    def test_top_level_source_cannot_write_a_host_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "must-not-exist"
            code = f'from pathlib import Path\nPath({str(target)!r}).write_text("BAD")\ndef slug(text):\n    return text\n'
            with self.assertRaises(ValueError):
                self.validate({"src/textutil.py": code})
            self.assertFalse(target.exists())

    def test_serializer_substitution_is_not_an_observation_capability(self):
        code = 'import sys\nsetattr(sys.modules["__main__"], "canonical", lambda value: b"forged")\ndef slug(text):\n    return text\n'
        with self.assertRaises(ValueError):
            self.validate({"src/textutil.py": code})

    def test_reflective_attribute_access_is_denied(self):
        with self.assertRaises(ValueError):
            self.validate({"src/textutil.py":
                "def slug(text):\n    return text.__class__.__base__\n"})

    def test_dynamic_execution_is_denied_even_in_an_uncalled_branch(self):
        with self.assertRaises(ValueError):
            self.validate({"src/textutil.py":
                "def slug(text):\n    if False:\n        eval(text)\n    return text\n"})

    def test_decorators_and_classes_cannot_execute_during_module_loading(self):
        for code in (
            "@open(1)\ndef slug(text):\n    return text\n",
            "class SideEffect:\n    pass\ndef slug(text):\n    return text\n",
        ):
            with self.subTest(code=code), self.assertRaises(ValueError):
                self.validate({"src/textutil.py": code})

    def test_missing_case_function_does_not_become_an_empty_success(self):
        with self.assertRaises(ValueError):
            self.validate({"src/textutil.py": "def other(text):\n    return text\n"})

    def test_parent_package_side_effects_are_not_silently_ignored(self):
        with self.assertRaises(ValueError):
            self.validate({
                "src/pkg/__init__.py": "import os\nos._exit(0)\n",
                "src/pkg/textutil.py": "def slug(text):\n    return text\n",
            }, module="pkg.textutil")

    def test_source_assignment_cannot_mutate_a_trusted_module(self):
        with self.assertRaises(ValueError):
            self.validate({"src/textutil.py":
                "import json\njson.dumps = str\ndef slug(text):\n    return text\n"})

    def test_unrelated_test_files_remain_inert_outside_import_roots(self):
        self.assertIsNone(self.validate({
            "src/textutil.py": "def slug(text):\n    return text.strip()\n",
            "tests/test_something.py": "import unittest\nraise SystemExit(0)\n",
        }))

    def test_special_module_globals_cannot_change_real_python_semantics(self):
        with self.assertRaises(ValueError):
            self.validate({"src/textutil.py":
                '__builtins__ = {}\ndef slug(text):\n    return len(text)\n'})

    def test_runtime_annotations_are_outside_the_inert_function_profile(self):
        with self.assertRaises(ValueError):
            self.validate({"src/textutil.py":
                'def annotation():\n    while True:\n        pass\ndef slug(text: annotation()):\n    return text.strip()\n'})

    def test_mutable_defaults_are_not_recreated_as_different_python_state(self):
        with self.assertRaises(ValueError):
            self.validate({"src/textutil.py":
                'def slug(text, seen=[]):\n    seen.append(text)\n    return len(seen)\n'})

    def test_invalid_duplicate_parameters_never_become_a_valid_function(self):
        with self.assertRaises(ValueError):
            self.validate({"src/textutil.py":
                'def slug(text, text):\n    return text.strip()\n'})

    def test_identity_of_non_singleton_data_is_not_an_oracle_contract(self):
        with self.assertRaises(ValueError):
            self.validate({"src/textutil.py":
                'def slug(text):\n    left = [text]\n    right = [text]\n    return left is right\n'})

    def test_source_cannot_shadow_the_selected_standard_library(self):
        with self.assertRaises(ValueError):
            self.validate({
                "src/textutil.py": "import json\ndef slug(text):\n    return json.loads(text)\n",
                "src/json.py": "def loads(text):\n    return text\n",
            })

    def test_syntax_diagnostics_do_not_disclose_candidate_source(self):
        with warnings.catch_warnings(record=True) as diagnostics:
            warnings.simplefilter("always")
            with self.assertRaises(ValueError):
                self.validate({"src/textutil.py":
                    'def slug(text):\n    return text is "private candidate literal"\n'})
        self.assertEqual([], diagnostics)


class ObservationVersionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = recipe_support.GeneralRecipeTests(
            "test_source_is_actual_git_commit_tree_and_independently_exported_bytes"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_old_manifest_cannot_silently_select_the_new_execution_model(self):
        profile = self.fixture.profile()
        row = json.loads(profile.manifest_bytes())
        row["schema"] = "aioa.python-repository-recipe.v1"
        with self.assertRaises(ValueError):
            type(profile).from_manifest(json.dumps(row).encode())

    def test_old_report_is_rejected_even_if_values_match_the_oracle(self):
        *_, patch, _archive = self.fixture.proposal()
        profile = self.fixture.profile()
        report = {
            "schema": "aioa.python-observation.v1",
            "stage": "FAST_TESTS", "profile_digest": profile.digest,
            "patchset_sha256": patch.patchset_sha256,
            "results": [
                {"case_id": "spaces", "kind": "returned", "value": "one-two"},
                {"case_id": "empty", "kind": "returned", "value": ""},
            ],
        }
        with self.assertRaises(ValueError):
            profile.decode_observation(json.dumps(report) + "\n", "FAST_TESTS", patch)
