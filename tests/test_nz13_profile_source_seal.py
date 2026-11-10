"""Normal-function and renderer policies belong to the existing Native seal."""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from runtime.meta_hackathon.runtime_adapter import SOURCE_FILES

REQUIRED = {
    'runtime/mission/python_test_contracts.py',
    'runtime/mission/dependency_lock.py', 'runtime/mission/function_isolation.py',
    'runtime/mission/python_function_worker.py', 'runtime/mission/python_function_child.py',
    'runtime/mission/repository_worker.py', 'runtime/mission/render_recipe.py',
    'runtime/mission/render_worker.py', 'runtime/mission/render_runtime.py',
    'runtime/mission/render_observation.py', 'runtime/mission/repair_validation.py',
    'runtime/mission/worker.py', 'runtime/mission/codex_worker.py',
    'runtime/mission/patchset.py', 'runtime/mission/repair.py',
    'runtime/mission/patch_capsule.py', 'runtime/mission/coding_tasks.py',
    'runtime/mission/target_settlement.py',
    'runtime/mission/target_projection.py',
    'runtime/mission/portable_target.py',
}


# Fixed reviewed pre-G08 paths and recomputed F11 physical/Core closure.
PRE_G08_SOURCE_FILES = {
    'runtime/meta_hackathon/runtime_adapter.py',
    'runtime/meta_hackathon/mission_service.py',
    'runtime/meta_hackathon/mission_read_offline.py',
    'runtime/providers/meta_model_api.py',
    'runtime/browser_agent/chrome_read_adapter.py',
    'runtime/core_admission.py',
    'runtime/providers/config.py',
    'runtime/mission/warrant.py',
    'runtime/webapp.py',
    'web/app.js',
    'web/meta_mission.js',
    'web/index.html',
    'web/styles.css',
    'runtime/providers/meta_receipts.py',
    'runtime/browser_agent/chrome_process_read.py',
    'runtime/mission/governor.py',
    'runtime/providers/exact.py',
    'runtime/providers/tool_calling.py',
    'runtime/memory_patch/persistence/ports.py',
    'runtime/memory_patch/contracts/serialization.py',
    'runtime/meta_hackathon/contracts.py',
    'runtime/meta_hackathon/muse_plan.py',
    'runtime/meta_hackathon/network_admission.py',
    'runtime/browser_agent/offline_adapter.py',
    'lab/archaioa/warrant.py',
    'lab/archaioa/authority.py',
    'lab/archaioa/decision_root.py',
    'runtime/mobile_gateway/__init__.py',
    'runtime/mobile_gateway/wire.py',
    'runtime/mobile_gateway/service.py',
    'protocol/mobile_mission_v1.json',
    'runtime/mobile_gateway/pairing.py',
    'protocol/mobile_pairing_v1.json',
    'runtime/memory_patch/audit.py',
    'runtime/memory_patch/persistence/idempotency.py',
    'runtime/memory_patch/contracts/records.py',
    'runtime/memory_patch/contracts/enums.py',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/Wire.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/TransportIdentity.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MobileClient.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MissionViewModel.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/Freshness.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MainActivity.kt',
    'clients/android/app/src/main/AndroidManifest.xml',
    'clients/android/app/src/main/res/xml/network_security_config.xml',
    'clients/android/app/src/main/res/xml/data_extraction_rules.xml',
    'LICENSE',
    'runtime/meta_hackathon/agent_operations.py',
    'runtime/mission/intent.py',
    'runtime/mission/tools.py',
    'runtime/mission/target_settlement.py',
    'runtime/mission/target_projection.py',
    'runtime/mission/portable_target.py',
    'runtime/mission/liability.py',
    'runtime/service_guard/service.py',
    'runtime/mission/project_recipe.py',
    'runtime/mission/project_worker.py',
    'runtime/mission/workspace_worker.py',
    'runtime/mission/sensorbridge_template.py',
    'runtime/mission/sensorbridge_checks.py',
    'runtime/mission/sandbox_linux.py',
    'runtime/mission/sandbox_worker.py',
    'runtime/mission/sandbox_contracts.py',
    'runtime/mission/native/worker_gate.c',
    'runtime/mission/native/bootstrap.c',
    'runtime/mission/git_publish.py',
    'runtime/mission/git_publish_worker.py',
    'runtime/mission/git_recipe.py',
    'runtime/mission/git_worker.py',
    'runtime/mission/install_plan.py',
    'runtime/mcp_bridge/adapter.py',
    'runtime/mcp_bridge/policy.py',
    'runtime/mcp_bridge/read_ops.py',
    'runtime/mcp_bridge/contracts.py',
    'runtime/mcp_bridge/task_bus.py',
    'runtime/mobile_gateway/views_v2.py',
    'protocol/mobile_mission_v2.json',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/AgentMissionView.kt',
    'runtime/meta_hackathon/web_agent.py',
    'web/agent_mission.js',
    'clients/android/ANDROID_BUILD_INPUT_MANIFEST.json',
    'web/mobile_devices.js',
    'web/mobile_devices_dom.js',
    'web/qr.js',
    'runtime/mcp_bridge/github_remote.py',
    'runtime/meta_hackathon/github_write.py',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/PairingProtocol.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/TrustedHostStore.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/CosmicScreen.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/PairingProblem.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/SessionRecovery.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/RecoveryNetworkMonitor.kt',
    'clients/android/app/src/main/res/values/strings.xml',
    'clients/android/app/src/main/res/values-pl/strings.xml',
    'web/cosmic_tokens.css',
    'web/cosmic_space_grotesk.ttf',
    'web/cosmic_manrope.ttf',
    'web/cosmic_ibm_plex_mono.ttf',
    'web/cosmic_fonts_ofl.txt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/CosmicTheme.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/PairingDelivery.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/CosmicMissionPages.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/CosmicComponents.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/CosmicPresentation.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MissionUi.kt',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/TaskReadback.kt',
    'clients/android/app/src/main/res/values/cosmic_colors.xml',
    'clients/android/app/src/main/res/font/cosmic_space_grotesk.ttf',
    'clients/android/app/src/main/res/font/cosmic_manrope.ttf',
    'clients/android/app/src/main/res/font/cosmic_ibm_plex_mono.ttf',
    'clients/android/app/src/main/assets/licenses/cosmic_fonts_ofl.txt',
    'runtime/meta_hackathon/chat.py',
    'runtime/meta_hackathon/chat_session.py',
    'runtime/mobile_gateway/chat_views.py',
    'runtime/mobile_gateway/operator_chat.py',
    'runtime/mobile_gateway/chrome_console.py',
    'protocol/mobile_chat_v1.json',
    'web/mobile_chat.js',
    'clients/android/app/src/main/java/eu/sparkhat/aioa/companion/ChatView.kt',
    'runtime/mcp_bridge/native_read.py',
    'runtime/meta_hackathon/native_tools.py',
    'runtime/secret_redaction.py',
    'runtime/failure_boundary.py',
    'runtime/mission/python_test_contracts.py',
    'runtime/mission/dependency_lock.py',
    'runtime/mission/function_isolation.py',
    'runtime/mission/python_function_worker.py',
    'runtime/mission/python_function_child.py',
    'runtime/mission/repository_worker.py',
    'runtime/mission/render_recipe.py',
    'runtime/mission/render_worker.py',
    'runtime/mission/render_runtime.py',
    'runtime/mission/render_observation.py',
    'runtime/mission/repair_validation.py',
    'runtime/mission/worker.py',
    'runtime/mission/codex_worker.py',
    'runtime/mission/patchset.py',
    'runtime/mission/repair.py',
    'runtime/mission/patch_capsule.py',
    'runtime/mission/coding_tasks.py',
    'runtime/mobile_gateway/desktop.py',
    'runtime/critical_loop/preset.py',
    'web/white-hole.svg',
    'runtime/meta_hackathon/advisory.py',
    'runtime/tools/command_grammar.py',
    'runtime/knowledge/grammar/command_patterns.json',
    'runtime/communication/contracts.py',
    'runtime/communication/canonical_mime.py',
    'runtime/communication/__init__.py',
    'runtime/critical_loop/cpt/__init__.py',
    'runtime/critical_loop/cpt/sanitizer.py',
    'runtime/critical_loop/cpt/schema.py',
    'runtime/critical_loop/cpt/templates.py',
    'runtime/critical_loop/cpt/transformer.py',
    'runtime/critical_loop/cpt/preview.py',
    'runtime/critical_loop/redaction.py',
    'runtime/critical_loop/__init__.py',
    'runtime/main.py',
}

G08_REQUIRED = {
    'lab/archaioa/__init__.py',
    'lab/archaioa/attenuation.py',
    'lab/archaioa/authority.py',
    'lab/archaioa/canonical.py',
    'lab/archaioa/contracts.py',
    'lab/archaioa/decision_binding.py',
    'lab/archaioa/decision_root.py',
    'lab/archaioa/evidence.py',
    'lab/archaioa/faults.py',
    'lab/archaioa/liability.py',
    'lab/archaioa/outcome.py',
    'lab/archaioa/taint.py',
    'lab/archaioa/task_semantics.py',
    'lab/archaioa/warrant.py',
    'runtime/__init__.py',
    'runtime/core_admission.py',
    'runtime/evidence_admission.py',
    'runtime/failure_boundary.py',
    'runtime/memory_patch/__init__.py',
    'runtime/memory_patch/adapters/cockroach/repositories.py',
    'runtime/memory_patch/audit.py',
    'runtime/memory_patch/contract.py',
    'runtime/memory_patch/contracts/enums.py',
    'runtime/memory_patch/contracts/identities.py',
    'runtime/memory_patch/contracts/records.py',
    'runtime/memory_patch/contracts/scope.py',
    'runtime/memory_patch/contracts/serialization.py',
    'runtime/memory_patch/errors.py',
    'runtime/memory_patch/persistence/idempotency.py',
    'runtime/memory_patch/persistence/ports.py',
    'runtime/memory_patch/persistence/retry.py',
    'runtime/memory_patch/retrieval/embeddings.py',
    'runtime/memory_patch/source_lineage.py',
    'runtime/mission/__init__.py',
    'runtime/mission/completion.py',
    'runtime/mission/contracts.py',
    'runtime/mission/governor.py',
    'runtime/mission/intent.py',
    'runtime/mission/job_contracts.py',
    'runtime/mission/jobs.py',
    'runtime/mission/liability.py',
    'runtime/mission/lite_contracts.py',
    'runtime/mission/portable_target.py',
    'runtime/mission/sandbox_contracts.py',
    'runtime/mission/target_projection.py',
    'runtime/mission/target_settlement.py',
    'runtime/mission/tools.py',
    'runtime/mission/warrant.py',
    'runtime/nonzero_cloudops/__init__.py',
    'runtime/nonzero_cloudops/adapters/__init__.py',
    'runtime/nonzero_cloudops/adapters/portable.py',
    'runtime/nonzero_cloudops/adapters/resources.py',
    'runtime/nonzero_cloudops/contract.py',
    'runtime/nonzero_cloudops/models/__init__.py',
    'runtime/nonzero_cloudops/models/authority.py',
    'runtime/nonzero_cloudops/models/contracts.py',
    'runtime/nonzero_cloudops/models/digest.py',
    'runtime/nonzero_cloudops/models/enums.py',
    'runtime/nonzero_cloudops/models/errors.py',
    'runtime/nonzero_cloudops/models/identifiers.py',
    'runtime/nonzero_cloudops/models/public_enums.py',
    'runtime/nonzero_cloudops/models/redaction.py',
    'runtime/nonzero_cloudops/models/transitions.py',
    'runtime/nonzero_cloudops/models/uuid7.py',
    'runtime/nonzero_cloudops/models/validation.py',
    'runtime/nonzero_cloudops/provenance.py',
    'runtime/nonzero_cloudops/service.py',
    'runtime/nonzero_cloudops/state/__init__.py',
    'runtime/nonzero_cloudops/state/files.py',
    'runtime/providers/__init__.py',
    'runtime/providers/aureon_provider.py',
    'runtime/providers/base.py',
    'runtime/providers/config.py',
    'runtime/providers/exact.py',
    'runtime/providers/gemini_provider.py',
    'runtime/providers/live_gate.py',
    'runtime/providers/messages.py',
    'runtime/providers/nebius.py',
    'runtime/providers/nvidia.py',
    'runtime/providers/openai_compatible.py',
    'runtime/providers/safety.py',
    'runtime/runtime_paths.py',
    'runtime/secret_redaction.py',
    'runtime/service_guard/__init__.py',
    'runtime/service_guard/contracts.py',
    'runtime/service_guard/https_transport.py',
    'runtime/service_guard/target.py',
    'runtime/tools/__init__.py',
    'runtime/tools/provenance.py',
}


class ProfileSourceSealTests(unittest.TestCase):
    def test_all_profile_helpers_and_core_validation_authority_are_covered_by_one_existing_seal(self):
        self.assertFalse(REQUIRED - set(SOURCE_FILES), 'Unsealed function/render/Core policy helpers')

    def test_profile_seal_has_no_duplicate_or_private_paths_and_keeps_existing_core_boundaries(self):
        self.assertEqual(len(SOURCE_FILES), len(set(SOURCE_FILES)))
        for name in SOURCE_FILES:
            path = PurePosixPath(name)
            self.assertFalse(path.is_absolute())
            self.assertNotIn('..', path.parts)
            self.assertNotIn(path.name, {'REVIEW_NZ12_MAIN_RANGE.md', 'REVIEW_NZ12_RAW.json'})
            self.assertNotIn(path.suffix, ('.pem', '.sqlite3', '.db'))
        self.assertTrue({'runtime/core_admission.py', 'runtime/mission/warrant.py',
                         'runtime/mission/intent.py', 'runtime/mission/sandbox_linux.py',
                         'runtime/mission/native/bootstrap.c', 'runtime/failure_boundary.py'} <= set(SOURCE_FILES))

    def _require_native_coverage(self, paths):
        self.assertEqual(len(paths), len(set(paths)), 'Duplicate source paths')
        self.assertFalse(PRE_G08_SOURCE_FILES - set(paths), 'Previously sealed source paths removed')
        self.assertFalse(G08_REQUIRED - set(paths), 'Unsealed physical/Core source paths')

    def test_reviewed_physical_core_closure_and_all_previous_paths_are_sealed(self):
        self._require_native_coverage(SOURCE_FILES)

    def test_native_membership_control_rejects_one_inert_omission(self):
        self._require_native_coverage(SOURCE_FILES)
        omitted = tuple(p for p in SOURCE_FILES if p != 'runtime/nonzero_cloudops/state/files.py')
        with self.assertRaisesRegex(AssertionError, 'Unsealed physical/Core source paths'):
            self._require_native_coverage(omitted)

    def test_native_membership_control_rejects_one_inert_duplicate(self):
        self._require_native_coverage(SOURCE_FILES)
        with self.assertRaisesRegex(AssertionError, 'Duplicate source paths'):
            self._require_native_coverage((*SOURCE_FILES, 'runtime/nonzero_cloudops/state/files.py'))

    def test_fresh_source_import_and_status_are_inert_without_optional_domain_extras(self):
        project = Path(__file__).resolve().parents[1]
        code = r"""
import json, runpy, sys
from importlib.abc import MetaPathFinder
from pathlib import Path
project = Path(sys.argv[1])
support = runpy.run_path(str(project / 'tests/nz13_source_only_imports.py'))
support['install'](project)
sys.path.insert(0, str(project))
attempted = []
class OptionalUnavailable(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.', 1)[0] in ('pydantic', 'uuid6'):
            attempted.append(fullname)
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, OptionalUnavailable())
from runtime.meta_hackathon import runtime_adapter as api
assert all(type(p) is str for p in api.SOURCE_FILES)
assert not any(m.startswith(('nonzero_cloudops', 'runtime.nonzero_cloudops')) for m in sys.modules)
from nonzero_cloudops import module_descriptor
status = module_descriptor()
assert status['available'] is False
assert status['availability_code'] == 'NONZERO_OPTIONAL_DEPENDENCIES_UNAVAILABLE'
assert not attempted and 'pydantic' not in sys.modules and 'uuid6' not in sys.modules
assert not any(m.startswith(('nonzero_cloudops.models', 'runtime.nonzero_cloudops.models')) for m in sys.modules)
print(json.dumps({'inert_import': True, 'available': status['available'], 'optional_import_attempts': attempted}))
"""
        with TemporaryDirectory() as folder:
            root = Path(folder)
            result = subprocess.run(
                [sys.executable, '-I', '-B', '-S', '-c', code, str(project)],
                cwd=root, env={'PATH': os.defpath, 'HOME': str(root), 'TMPDIR': str(root),
                               'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'},
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual({'inert_import': True, 'available': False,
                              'optional_import_attempts': []}, json.loads(result.stdout))
            self.assertEqual([], list(root.iterdir()))
