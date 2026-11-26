"""One admitted D render and read-only evidence checks for a dedicated operator host.

The execute function is called by an existing admitted Core session. The CLI
only verifies previously exported evidence; it cannot mint a session or warrant.
"""
import argparse
import base64
import json
import os
import re
import time
from pathlib import Path

from lab.archaioa.warrant import EffectWarrant
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.render_recipe import HtmlRenderRecipe
from runtime.mission.repair_validation import CoreSandboxValidation, PreparedValidationStep
from runtime.mission.sandbox_contracts import SandboxOperation
from runtime.mission.sandbox_linux import exact_cgroup
from runtime.mobile_gateway.wire import verify
from scripts.unification.noble_preflight import command, compare_manifest, digest, host_gaps, observe, pinned_json, require


def recipe():
    html = b'<!doctype html><meta charset="utf-8"><title>Offline render</title><h1>Core render verified</h1>'
    return HtmlRenderRecipe((('index.html', html),), (320, 200), 'Offline render', 'Core render verified')


def execute_admitted(validator, principal, step, *, manifest_path, manifest_sha256, management_receipt):
    obs = observe()
    require(not host_gaps(obs), 'BLOCKED_HOST')
    manifest = pinned_json(manifest_path, manifest_sha256)
    compare_manifest(manifest, obs, management_receipt)
    pin = manifest['g04']
    now = time.time()
    require(type(pin['start_unix']) is int and type(pin['expiry_unix']) is int
            and pin['start_unix'] <= now and now + 180 <= pin['expiry_unix']
            and pin['expiry_unix'] - pin['start_unix'] <= 1800 and pin['uid'] == os.getuid(),
            'G04_OPERATOR_WINDOW')
    unit = pin['unit']
    require(isinstance(unit, str) and re.fullmatch(r'aioa-g04-[a-f0-9]{32}\.service', unit), 'UNIT_PIN')
    own_cgroup = Path('/proc/self/cgroup').read_text().strip()
    require(own_cgroup == exact_cgroup(unit).removesuffix('/work'), 'WRONG_SUPERVISOR_UNIT')
    for prop, value in [('RuntimeMaxUSec', '3min'), ('PrivateNetwork', 'yes'), ('NoNewPrivileges', 'yes')]:
        require(command('/usr/bin/systemctl', '--user', 'show', unit, '--property=' + prop, '--value') == value,
                'G04_SUPERVISOR_' + prop)
    require(type(validator) is CoreSandboxValidation and type(step) is PreparedValidationStep
            and step.route.journal is validator.journal and step.stage == 'RENDER', 'EXISTING_CORE_REQUIRED')
    fixed = recipe()
    op = step.arguments['operation']
    cfg = step.route.sandbox_config_for_operation(op)
    profile = cfg.profile()
    public_key = validator.render_capsules.identity.spki
    require(digest(base64.b64decode(public_key, validate=True)) == pin['core_spki_sha256']
            and step.arguments['warrant'].digest() == pin['warrant']
            and step.arguments['session_id'] == pin['session_id'], 'G04_ENROLLMENT_BINDING')
    require(cfg.profile_digest == canonical_sha256(profile) == pin['profile_sha256']
            and profile['resource_profile'] == 'HEADLESS_RENDER_V3' and profile['network'] == 'OFF'
            and profile['ipc_profile'] == 'RENDER_UNIX_MOJO_V1'
            and profile['runtime']['/opt/google/chrome/chrome']['sha256'] == pin['chrome_sha256']
            and canonical_sha256(profile['runtime']) == pin['runtime_sha256']
            and profile['worker_sha256'] == pin['keeper_sha256']
            and profile['native']['final_filter'] == pin['final_filter_sha256']
            and profile['native']['setup_filter'] == pin['setup_filter_sha256']
            and fixed.digest == pin['recipe_sha256']
            and 0 < op['payload']['timeout_ms'] <= 20000, 'G04_RENDER_PINS')
    # A private precreated root owned by this sandbox is already required by its
    # preparation. Consume the one-session evidence marker before entering Core.
    # Any ambiguous outcome leaves both the marker and the authoritative journal.
    warrant = step.arguments['warrant']
    fresh_intent = validator.journal._run(principal, Capability.COMMIT,
                                          lambda tx: validator.journal._load(tx, warrant)[1] is None)
    require(fresh_intent and not any(cfg.root.glob('run-*')), 'FRESH_RENDER_STATE_REQUIRED')
    evidence_fd = os.open(cfg.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(evidence_fd)
        require(info.st_uid == os.getuid() and info.st_mode & 0o777 == 0o700, 'FRESH_PRIVATE_RENDER_ROOT')
        fd = os.open('g04-session-consumed', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=evidence_fd)
        with os.fdopen(fd, 'wb') as marker:
            marker.write(manifest_sha256.encode('ascii'))
            marker.flush()
            os.fsync(marker.fileno())
        os.fsync(evidence_fd)
    finally:
        os.close(evidence_fd)
    return validator.render(principal, step, fixed)


def cold_read(validator, read_principal, warrant_digest):
    """Use after restarting the existing Core store with a READ principal only."""
    require(type(validator) is CoreSandboxValidation, 'EXISTING_CORE_REQUIRED')
    return validator.read_render(read_principal, warrant_digest)


def verify_export(pins, record, raw, spki):
    require(digest(base64.b64decode(spki, validate=True)) == pins['core_spki_sha256'], 'G04_SIGNER')
    proof = dict(record)
    signature = proof.pop('signature')
    verify(spki, signature, proof)
    require(proof['schema'] == 'aioa.trusted-render-validation.v1' and proof['status'] == 'PASS'
            and proof['authority'] == 'NONE' and proof['evidence_digest'] == digest(raw), 'G04_SIGNED_RECEIPT')
    receipt = json.loads(raw)
    op = receipt['request']['operation']
    operation = SandboxOperation.parse(op)
    payload = op['payload']
    require(operation.digest == receipt['operation_digest'] and payload['sandbox_profile_digest'] == pins['profile_sha256']
            and payload['resource_profile'] == 'HEADLESS_RENDER_V3'
            and payload['recipe_id'] == 'recipe:html-' + pins['recipe_sha256'][:24], 'G04_RECEIPT_OPERATION')
    warrant = EffectWarrant.from_dict(proof['warrant'])
    require(warrant.digest() == pins['warrant'] == proof['warrant_digest'] == receipt['warrant_digest']
            and receipt['request']['session_id'] == pins['session_id']
            and warrant.operation_hash == proof['operation_digest'] == receipt['operation_digest']
            and proof['sandbox_profile_digest'] == pins['profile_sha256'] == receipt['profile_digest'],
            'G04_RECEIPT_BINDINGS')
    require(receipt['status'] == 'READBACK_VERIFIED' and all(receipt[name] is True for name in
            ('unit_terminal_observed', 'project_code_started', 'cgroup_absent_after_cleanup',
             'cgroup_populated_zero_directly_observed')), 'G04_CLEANUP')
    obs = receipt['observations']
    cg = obs['worker_gate']['work_cgroup']
    path = f"/user.slice/user-{pins['uid']}.slice/user@{pins['uid']}.service/app.slice/{receipt['unit']}/work"
    require(re.fullmatch(r'aioa-sandbox-[a-f0-9]{32}\.service', receipt['unit'])
            and cg == '/sys/fs/cgroup' + path and obs['peer']['cgroup'] == '0::' + path
            and obs['peer']['uid'] == pins['uid'] and obs['peer']['pidfd_pinned'] is True
            and obs['worker_gate']['before_exec_placement'] is True
            and obs['worker_populated_zero_after_readback'] is True
            and obs['worker_populated_zero_before_readback'] is True, 'G04_KEEPER_OR_CGROUP')
    require(set(obs['namespaces']) == {'user', 'mnt', 'pid', 'net', 'ipc', 'uts', 'cgroup'}
            and all(v['host'] != v['worker'] for v in obs['namespaces'].values())
            and obs['privileges']['NoNewPrivs'] == '1' and obs['privileges']['Seccomp'] == '2'
            and int(obs['privileges']['CapEff'], 16) == 0, 'G04_ISOLATION')
    fixed = recipe()
    oracle = fixed.verify_observation(obs['worker_terminal']['stdout'].encode())
    require(fixed.digest == pins['recipe_sha256'] == proof['profile_digest'] and oracle == proof['oracle'],
            'G04_ORACLE')
    return {'result': 'SIGNED_RENDER_AND_KERNEL_RECEIPT_VERIFIED', 'receipt_sha256': digest(raw),
            'warrant_digest': warrant.digest(), 'active_stop': 'SEPARATE_EVIDENCE_REQUIRED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--cold-record', required=True)
    parser.add_argument('--broker-receipt', required=True)
    parser.add_argument('--public-spki', required=True)
    args = parser.parse_args()
    manifest = pinned_json(args.manifest, args.manifest_sha256)
    def bounded(path, size):
        with Path(path).open('rb') as stream:
            raw = stream.read(size + 1)
        require(0 < len(raw) <= size, 'G04_EXPORT_BOUND')
        return raw
    result = verify_export(manifest['g04'], json.loads(bounded(args.cold_record, 8192)),
                           bounded(args.broker_receipt, 1048576),
                           bounded(args.public_spki, 512).decode('ascii').strip())
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
