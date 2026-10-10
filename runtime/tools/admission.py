"""Legacy public tools fail closed; approved immutable public inputs remain readable."""
from hashlib import sha256
from pathlib import PurePosixPath
from types import MappingProxyType
import os
import stat


class ReadDenied(ValueError):
    pass


class PublicFileReads:
    """Trusted host supplies exact public file digests; model cannot extend policy.

    No recursive directory scan, ambient cwd/HOME, symlink/hardlink or special
    file reads. Hash mismatch blocks changed content before exposing any bytes.
    Approval of public contents is a host responsibility, not generic DLP.
    """
    def __init__(self, root, files=None):
        if files is None:files={}
        if type(files) is not dict or len(files)>128:raise ReadDenied('INVALID_READ_POLICY')
        for name,digest in files.items():
            self._relative(name)
            if type(digest) is not str or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
                raise ReadDenied('INVALID_READ_POLICY')
        self.root=root.absolute()
        self.files=MappingProxyType(dict(files))

    @staticmethod
    def _relative(value):
        if type(value) is not str or not 0<len(value)<=256 or '\\' in value or '\x00' in value:
            raise ReadDenied('READ_PATH_DENIED')
        path=PurePosixPath(value)
        if path.is_absolute() or '..' in path.parts or not path.parts or str(path)!=value:
            raise ReadDenied('READ_PATH_DENIED')
        return path

    def read(self, name):
        path=self._relative(name)
        if name not in self.files:raise ReadDenied('READ_ALLOWLIST_REQUIRED')
        descriptors=[]
        try:
            fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
            descriptors.append(fd)
            for component in self.root.parts[1:]:
                if component in {'.','..'}:raise ReadDenied('READ_PATH_DENIED')
                fd=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
                descriptors.append(fd)
            for component in path.parts[:-1]:
                fd=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
                descriptors.append(fd)
            fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=fd)
            descriptors.append(fd);before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size>8192:
                raise ReadDenied('READ_FILE_DENIED')
            data=os.read(fd,8193);after=os.fstat(fd)
            # Access time can change because of this read; identity/content must not.
            stable=('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
            if len(data)>8192 or any(getattr(before,k)!=getattr(after,k) for k in stable) or sha256(data).hexdigest()!=self.files[name]:
                raise ReadDenied('READ_CONTENT_CHANGED')
            return data.decode('utf-8')
        except (OSError,UnicodeError):
            raise ReadDenied('READ_FILE_DENIED') from None
        finally:
            for fd in reversed(descriptors):os.close(fd)

    def execute(self, action):
        if action['action']=='read_file':
            content=self.read(action.get('path'))
            return {'success':True,'path':action['path'],'content':content,'message':'Approved public input read.'}
        pattern=action.get('pattern');root=action.get('path','.')
        if type(pattern) is not str or not 0<len(pattern)<=128:raise ReadDenied('READ_QUERY_DENIED')
        if root!='.':self._relative(root)
        matches=[];used=0
        selected=[name for name in self.files if root=='.' or name==root or name.startswith(root+'/')]
        if not selected:raise ReadDenied('READ_ALLOWLIST_REQUIRED')
        for name in selected:
            text=self.read(name);used+=len(text.encode())
            if used>65536:raise ReadDenied('READ_LIMIT_EXCEEDED')
            for number,line in enumerate(text.splitlines(),1):
                if pattern in line:
                    matches.append({'path':name,'line_number':number,'line':line[:256]})
                    if len(matches)>=32:
                        return {'success':True,'matches':matches,'truncated':True,'message':'Bounded public input search.'}
        return {'success':True,'matches':matches,'truncated':False,'message':'Approved public input search.'}


def legacy_command_allowed(name, args):
    """Read/control-plane inventory, checked before any legacy handler executes."""
    verb=args.strip().split(' ',1)[0].lower()
    if name in {'help','status','tools','vault','providers','setup','review'}:return True
    if name=='model':return True  # Explicit local control-plane switch, never an effect grant.
    if name=='cpl':return True  # Separate exact advisory plan/nonce service; no tool executor.
    if name=='rhcsa':return verb in {'','status','savings','search','tag','exact','grep','filter','topic','commands','workflows','examples'}
    if name=='worker':return verb in {'','status','memory'}
    if name=='nonzero':return verb in {'','status','help','?'}
    if name=='memory-patch':return args.strip() in {'','status'}
    if name=='orchestrator':return verb in {'','status'}
    # HAT plaintext, private SCEMDA extraction and all unregistered writes stay disabled.
    return False
