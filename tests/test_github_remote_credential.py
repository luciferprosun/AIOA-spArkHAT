"""Offline credential narrowing; never use a configured GitHub credential."""
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


class GitHubCredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.root.chmod(0o700)
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pem=self.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption())
        (self.root/'private-key.pem').write_bytes(pem);(self.root/'private-key.pem').chmod(0o600)
        (self.root/'app.json').write_text(json.dumps({'schema':'aioa.github-app.v1','client_id':'Iv1.fixture',
                                                    'installation_id':73}))
        (self.root/'app.json').chmod(0o600)
        self.now=1793851200;self.calls=[]
        self.token='ghs_'+'x'*20  # Deterministic non-secret offline fixture.
        self.permissions={'contents':'write','pull_requests':'write','metadata':'read'}
        self.repositories=[{'id':1445911975,'full_name':'luciferprosun/AIOA-spArkHAT-Meta-Hackathon-2026'}]
        self.fail=False

    def transport(self,method,path,payload,bearer,cancel,timeout):
        self.calls.append((method,path,payload,bearer))
        if self.fail:raise TimeoutError('PRIVATE_PROVIDER_BODY_MUST_NOT_ESCAPE')
        if method=='POST':return 201,json.dumps({'token':self.token,'expires_at':datetime.fromtimestamp(
            self.now+3600,timezone.utc).isoformat().replace('+00:00','Z'),'permissions':self.permissions,
            'repository_selection':'selected','repositories':self.repositories}).encode()
        return 200,json.dumps({'total_count':len(self.repositories),'repositories':self.repositories}).encode()

    def provider(self):
        from runtime.mcp_bridge.github_remote import GitHubAppCredentialSource
        return GitHubAppCredentialSource(self.root,mode='OFFLINE_FIXTURE',transport=self.transport,clock=lambda:self.now)

    def mint(self):
        from runtime.providers.exact import CancellationToken
        return self.provider().mint(cancel=CancellationToken(),check=lambda:None)

    def test_scopes_token_to_exact_repository_and_minimum_permissions_with_signed_jwt(self):
        credential=self.mint()
        self.assertEqual({'repository_ids':[1445911975],
                          'permissions':{'contents':'write','pull_requests':'write'}},self.calls[0][2])
        self.assertEqual(('GET','/installation/repositories?per_page=100&page=1'),self.calls[1][:2])
        header,claims,signature=self.calls[0][3].split('.')
        decode=lambda x:base64.urlsafe_b64decode(x+'='*((-len(x))%4))
        self.assertEqual({'alg':'RS256','typ':'JWT'},json.loads(decode(header)))
        self.assertEqual({'iss':'Iv1.fixture','iat':self.now-60,'exp':self.now+120},json.loads(decode(claims)))
        self.key.public_key().verify(decode(signature),(header+'.'+claims).encode(),padding.PKCS1v15(),hashes.SHA256())
        self.assertEqual(self.token,credential.bearer)
        self.assertNotIn(self.token,repr(credential));self.assertNotIn(self.token,json.dumps(credential.evidence()))
        self.assertEqual('OFFLINE_FIXTURE',credential.evidence()['mode'])

    def test_extra_permission_or_repository_is_denied(self):
        for permissions,repositories in ((dict(self.permissions,workflows='write'),self.repositories),
                (self.permissions,self.repositories+[{'id':1247349659,'full_name':'luciferprosun/AIOA-spArkHAT'}])):
            with self.subTest(permissions=permissions,repositories=repositories):
                self.permissions,self.repositories=permissions,repositories
                with self.assertRaisesRegex(ValueError,'GITHUB_CREDENTIAL_SCOPE_DENIED'):self.mint()

    def test_private_files_required_and_live_transport_cannot_be_injected(self):
        (self.root/'private-key.pem').chmod(0o644)
        with self.assertRaisesRegex(ValueError,'GITHUB_PRIVATE_CREDENTIAL_REQUIRED'):self.mint()
        self.assertEqual([],self.calls)
        from runtime.mcp_bridge.github_remote import GitHubAppCredentialSource
        with self.assertRaises(ValueError):GitHubAppCredentialSource(self.root,mode='LIVE',transport=self.transport)

    def test_unknown_mint_is_not_retried_and_exception_does_not_leak_provider_text(self):
        self.fail=True
        with self.assertRaisesRegex(ValueError,'^GITHUB_CREDENTIAL_UNKNOWN_NO_RETRY$'):self.mint()
        self.assertEqual(1,len(self.calls))

    def test_each_operation_mints_a_fresh_short_lived_token_without_cached_secret(self):
        first=self.mint();self.now+=3601
        second=self.mint()
        self.assertGreater(second.expires_at,first.expires_at)
        self.assertEqual(2,sum(method=='POST' for method,_,_,_ in self.calls))
        self.assertNotIn('bearer',second.evidence());self.assertNotIn('token',vars(self.provider()))

    def test_current_opaque_installation_token_format_is_accepted_without_logging_it(self):
        # GitHub's 2026 stateless format is longer and contains JWT separators.
        self.token='ghs_12345_'+'.'.join(('synthetic_header', 'fixture_payload_'+'x'*900, 'fixture-signature'))
        credential=self.mint()
        self.assertEqual(self.token,credential.bearer)
        self.assertEqual(self.token,self.calls[-1][3])
        self.assertNotIn(self.token,repr(credential)+json.dumps(credential.evidence()))

    def test_invalid_opaque_token_is_denied_before_scope_request_without_secret_echo(self):
        for token in ('x'*8193, 'synthetic_fixture\r\nAuthorization: forged', 'short'):
            self.calls=[];self.token=token
            with self.assertRaisesRegex(ValueError,'^GITHUB_CREDENTIAL_SCOPE_DENIED$'):self.mint()
            self.assertEqual(1,len(self.calls))

    def test_missing_invalid_and_linked_private_keys_never_reach_network(self):
        import os
        key=self.root/'private-key.pem';original=key.read_bytes();target=self.root/'saved.pem'
        target.write_bytes(original);target.chmod(0o600)
        for kind in ('missing','invalid','symlink','hardlink'):
            if key.exists() or key.is_symlink():key.unlink()
            if kind=='invalid':key.write_bytes(b'not a private key');key.chmod(0o600)
            if kind=='symlink':key.symlink_to(target)
            if kind=='hardlink':os.link(target,key)
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'GITHUB_PRIVATE_CREDENTIAL_REQUIRED'):self.mint()
        self.assertEqual([],self.calls)

    def test_denied_or_rate_limited_mint_is_not_retried_or_logged(self):
        from runtime.mcp_bridge.github_remote import GitHubAppCredentialSource
        from runtime.providers.exact import CancellationToken
        for status in (401,403,429):
            calls=[]
            def denied(*args):calls.append(args[0]);return status,b'SYNTHETIC_SENSITIVE_BODY'
            source=GitHubAppCredentialSource(self.root,mode='OFFLINE_FIXTURE',transport=denied,clock=lambda:self.now)
            with self.assertRaisesRegex(ValueError,'^GITHUB_CREDENTIAL_UNKNOWN_NO_RETRY$'):
                source.mint(cancel=CancellationToken(),check=lambda:None)
            self.assertEqual(['POST'],calls)


if __name__=='__main__':unittest.main()
