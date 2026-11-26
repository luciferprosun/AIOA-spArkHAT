"""Review, execute once, or cold-read the existing Core's pinned official MCP receipt."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runtime.mcp_bridge import official_read as mcp
from runtime.meta_hackathon.native_authority import _private_bytes
from runtime.mobile_gateway import wire
from runtime.mobile_gateway.desktop import validate_existing_profile
from runtime.webapp import mobile_operator_client


def save(path, value):
    raw = wire.canonical(value)+b'\n'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def request(root, **value):
    reply = mobile_operator_client(root, value)
    if reply.get('ok') is not True:
        raise ValueError('CORE_REFUSED_OR_UNKNOWN: '+str(reply.get('error')))
    return reply['data']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'execute', 'readback'])
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--credential-id', help='Numeric ID of the owner-reviewed one-repository fine-grained token')
    parser.add_argument('--approve-sha256', help='Exact digest from the reviewed prepare result')
    args = parser.parse_args()
    root = args.state_dir.absolute()
    validate_existing_profile(root)
    directory = root/'official-mcp-read'
    info = directory.lstat()
    if directory.resolve() != directory or not directory.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('PRIVATE_EVIDENCE_DIRECTORY_REQUIRED')
    if args.action == 'prepare':
        if not re.fullmatch('[0-9]{1,24}', args.credential_id or '') or args.approve_sha256:
            parser.error('prepare requires --credential-id')
        token = _private_bytes(str(directory/'read-token'), 512).rstrip(b'\n')
        settings_path = directory/'window.json'
        if not settings_path.exists():
            start = int(time.time())
            save(settings_path, {'credential_id': args.credential_id, 'credential_sha256': wire.digest(token),
                                 'credential_scope': mcp.SCOPE, 'starts_at': start, 'expires_at': start+1800})
        reply = request(root, op='tool_read_prepare', operation=mcp.OPERATION)
        if reply['permit']['credential_id'] != args.credential_id:
            raise ValueError('CREDENTIAL_ID_CHANGED')
        # All fields required for the real operator review, including the UTC window.
        print(json.dumps(reply, indent=2))
    elif args.action == 'execute':
        if not wire.HEX64.fullmatch(args.approve_sha256 or '') or args.credential_id:
            parser.error('execute requires the reviewed --approve-sha256')
        approval = request(root, op='tool_read_approve', operation=mcp.OPERATION,
                           permit_digest=args.approve_sha256)
        save(directory/'signed-approval.json', approval)
        data = request(root, op='tool_read', operation=mcp.OPERATION, request_id=mcp.REQUEST_ID,
                       approval=approval)
        save(directory/'signed-result.json', data)
        print('SIGNED_RESULT', wire.digest(wire.canonical(data)), 'request', mcp.REQUEST_ID)
    else:
        if args.approve_sha256 or args.credential_id:
            parser.error('readback takes only --state-dir')
        result = request(root, op='tool_readback', request_id=mcp.REQUEST_ID)
        if 'receipt' not in result:
            print(result['state'], 'automatic_retry=false')
            return 2
        status = request(root, op='operator_auth_status')
        if result['receipt']['core_instance_id'] == status['core_instance_id']:
            raise ValueError('COLD_CORE_INSTANCE_REQUIRED')
        if result['receipt']['transport'] != mcp.TRANSPORT:
            raise ValueError('ORIGINAL_MCP_RECEIPT_REQUIRED')
        observed = (directory/'signed-result.json')
        if observed.exists() and wire.strict_json(_private_bytes(str(observed), 32768), limit=wire.RESPONSE_LIMIT) != result:
            raise ValueError('SIGNED_READBACK_CHANGED')
        stored = directory/'cold-result.json'
        if stored.exists():
            earlier = wire.strict_json(_private_bytes(str(stored), wire.RESPONSE_LIMIT), limit=wire.RESPONSE_LIMIT)
            if earlier.get('result') != result:
                raise ValueError('COLD_READBACK_CHANGED')
        else:
            save(stored, {'result': result, 'readback_core_instance_id': status['core_instance_id']})
        print('COLD_VERIFIED', wire.digest(wire.canonical(result)), 'request', mcp.REQUEST_ID)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
