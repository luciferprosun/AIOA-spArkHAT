"""Passive, redacted mobile doctor. No network, subprocess or Tailscale mutation.

Optionally accepts an operator-produced status/serve JSON envelope on stdin.
Observed Android OS is NOT confirmation of this new phone or of trusted TLS.
"""
import argparse
import json
from pathlib import Path
import sys

PROTECTED_PORTS = (4314,4315,4316,4321,18766)


def report(status=None, serve=None, *, listening_ports=()):
    status = status if type(status) is dict else {}
    self_node = status.get('Self') if type(status.get('Self')) is dict else {}
    peers = status.get('Peer') if type(status.get('Peer')) is dict else {}
    android = any(type(p) is dict and p.get('OS') == 'android' and p.get('Online') is True
                  for p in peers.values())
    serve_present = type(serve) is dict and any(type(serve.get(k)) is dict and bool(serve[k])
                                               for k in ('Web','TCP'))
    return {'schema':'aioa.mobile.doctor.v1','readiness':'BLOCKED_EXTERNAL',
        'tailscale_status':'OBSERVED_RUNNING' if status.get('BackendState')=='Running' and self_node.get('Online') is True else 'UNKNOWN',
        'android_peer_observed':android,'new_android_peer_confirmed':False,
        'serve_configuration_observed':serve_present,'host_tls_verified':False,
        'gateway_protocol':'SOURCE_READY','gateway_remote':'REMOTE_DEPLOYMENT_BLOCKED',
        'apk_status':'APK_BUILD_BLOCKED_TOOLCHAIN','phone_paired':False,
        'protected_port_listeners':{str(p):p in listening_ports for p in PROTECTED_PORTS},
        'tailscale_mutations':0,'network_probes':0,'identifiers_redacted':True}


def passive_listeners():
    ports = set()
    for filename in ('/proc/net/tcp','/proc/net/tcp6'):
        try:
            # Local kernel socket table only; discard addresses and process IDs.
            for line in Path(filename).read_text().splitlines()[1:]:
                parts = line.split()
                if len(parts)>3 and parts[3]=='0A':ports.add(int(parts[1].rsplit(':',1)[1],16))
        except (OSError,ValueError):
            pass
    return ports


def main():
    parser=argparse.ArgumentParser(description='Passive redacted mobile readiness; never configures Tailscale')
    parser.add_argument('--tailscale-stdin',action='store_true',help='Read bounded operator-produced {status,serve} JSON; print booleans only')
    args=parser.parse_args()
    envelope={}
    if args.tailscale_stdin:
        try:
            raw=sys.stdin.buffer.read(1048577)
            if len(raw)<=1048576:
                value=json.loads(raw)
                if type(value) is dict:envelope=value
        except (ValueError,OSError):
            pass
    print(json.dumps(report(envelope.get('status'),envelope.get('serve'),
                            listening_ports=passive_listeners()),sort_keys=True,indent=2))
    return 2 # A redacted observation never qualifies the edge/phone by itself.


if __name__=='__main__':raise SystemExit(main())
