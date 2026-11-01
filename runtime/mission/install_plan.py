"""Versioned DEPENDENCY_INSTALL proposal using the existing tool family.

No package manager, network transport, authority backend or host installer is
constructed here. The offline adapter verifies an actual fixture artifact; it
explicitly does not install it or certify a wheel's executable contents.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256


def require(value, reason='DEPENDENCY_PLAN_DENIED'):
    if not value:raise ValueError(reason)


@dataclass(frozen=True,slots=True)
class DependencyInstallPlan:
    canonical_bytes: bytes

    def __post_init__(self):
        require(type(self.canonical_bytes) is bytes and 0<len(self.canonical_bytes)<=8192)
        p=json.loads(self.canonical_bytes)
        require(type(p) is dict and set(p)=={'schema','manager','package','version','artifact_sha256',
            'registry','license','workspace','venv_ref','network','timeout_seconds','memory_bytes','max_output_bytes'}
            and canonical_json_bytes(p)==self.canonical_bytes)
        require(p['schema']=='aioa.dependency-plan.v1' and p['manager']=='pip'
            and p['registry']=='https://pypi.org/simple' and p['workspace']=='fixture:sensorbridge'
            and p['venv_ref']=='workspace:.venv' and p['network']=='OFF')
        for key,pattern in {'package':r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',
            'version':r'[0-9]+(?:\.[0-9]+){1,3}(?:(?:a|b|rc)[0-9]+)?',
            'artifact_sha256':r'[a-f0-9]{64}','license':r'[A-Za-z0-9][A-Za-z0-9.+-]{0,63}'}.items():
            require(type(p[key]) is str and re.fullmatch(pattern,p[key]))
        require(type(p['timeout_seconds']) is int and 1<=p['timeout_seconds']<=20
            and type(p['memory_bytes']) is int and 1<=p['memory_bytes']<=268435456
            and type(p['max_output_bytes']) is int and 1<=p['max_output_bytes']<=16384)

    @classmethod
    def parse(cls,payload):
        require(type(payload) is dict)
        return cls(canonical_json_bytes(payload))

    @property
    def digest(self):return hashlib.sha256(self.canonical_bytes).hexdigest()

    def preview(self):
        return {'schema':'aioa.dependency-preview.v1','operation_class':'DEPENDENCY_INSTALL',
            'plan':json.loads(self.canonical_bytes),'plan_digest':self.digest,
            'approval_status':'NEEDS_HOST_APPROVAL','system_install':'DENY','install_enabled':False,
            'network_fetch_enabled':False,'license_acceptance':'NOT_GRANTED',
            'authority':'NONE','reason':'PROJECT_INSTALL_ADAPTER_AND_EXACT_CORE_WARRANT_NOT_BOUND'}


class OfflineInstallerAdapter:
    def __init__(self,root):
        self.root=Path(root).absolute();info=self.root.lstat()
        require(self.root.resolve()==self.root and stat.S_ISDIR(info.st_mode)
            and info.st_uid==os.getuid() and not info.st_mode&0o077,'INSTALL_PRIVATE_ROOT_REQUIRED')

    def inspect(self,plan,artifact):
        require(type(plan) is DependencyInstallPlan and type(artifact) is str
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',artifact),'INSTALL_ARTIFACT_DENIED')
        root=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        fd=None
        try:
            fd=os.open(artifact,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=root)
            before=os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_size<=1048576,
                    'INSTALL_ARTIFACT_TYPE_DENIED')
            data=bytearray()
            while len(data)<=1048576:
                part=os.read(fd,min(65536,1048577-len(data)))
                if not part:break
                data.extend(part)
            after=os.fstat(fd);named=os.stat(artifact,dir_fd=root,follow_symlinks=False)
            identity=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns,value.st_nlink)
            digest=hashlib.sha256(data).hexdigest()
            require(identity(before)==identity(after)==identity(named) and len(data)==before.st_size
                and digest==json.loads(plan.canonical_bytes)['artifact_sha256'],'INSTALL_ARTIFACT_CHANGED')
            return {'schema':'aioa.dependency-readback.v1','mode':'OFFLINE_FAKE_INSTALLER',
                'plan_digest':plan.digest,'artifact_sha256':digest,'artifact_readback_verified':True,
                'installed':False,'live_verified':False,'authority':'NONE','automatic_retry':False}
        finally:
            if fd is not None:os.close(fd)
            os.close(root)

    def dispatch(self,plan):
        raise ValueError('INSTALL_REQUIRES_EXACT_CORE_WARRANT_AND_PROJECT_ADAPTER')
