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
        self.token='ghs_OFFLINE_FIXTURE_ONLY'
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


if __name__=='__main__':unittest.main()
