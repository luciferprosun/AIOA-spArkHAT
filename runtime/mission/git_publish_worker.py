"""Registered commit-only recipe using the existing Git worker's bounded runner."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat


def require(ok, reason):
    if not ok:raise ValueError(reason)


def sha(data):return hashlib.sha256(data).hexdigest()
def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def main():
    plan_raw=Path('/inputs/plan.json').read_bytes();plan=json.loads(plan_raw)
    require(canonical(plan)==plan_raw and plan['schema']=='aioa.local-git-plan.v3'
        and plan['expected_revision']=='empty-repo-v1','GIT_PLAN_REQUIRED')
    require(sha(Path('/lib/git-core/git').read_bytes())==plan['git_sha256'],'GIT_BINARY_CHANGED')
    helper=runpy.run_path('/inputs/git_helpers.py',init_globals={'GIT_BINARY':'/lib/git-core/git','require':require})
    git,inspect_tree=helper['git'],helper['inspect_tree']
    root=Path('/work/repo');root.mkdir(mode=0o700)
    Path('/work/template').mkdir(mode=0o700)
    git('init','--object-format=sha1','--template=/work/template','--initial-branch='+plan['branch'],'.')
    identity=root.stat().st_dev,root.stat().st_ino
    for name,pin in plan['files'].items():
        require('/' not in name and not name.startswith(('.', '-')),'GIT_PATH_DENIED')
        data=Path('/inputs/source-'+name).read_bytes()
        require(len(data)==pin['bytes'] and sha(data)==pin['sha256'],'GIT_SOURCE_CHANGED')
        fd=os.open(root/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        try:
            require(os.write(fd,data)==len(data),'GIT_SHORT_WRITE');os.fsync(fd)
        finally:os.close(fd)
    inspect_tree(root)
    git('add','--',*sorted(plan['files']))
    require(git('write-tree').decode().strip()==plan['tree_sha'],'GIT_STAGED_TREE_CHANGED')
    diff=git('diff','--cached','--no-ext-diff','--no-textconv','--no-renames','--full-index','--')
    require(sha(diff)==plan['diff_sha256'] and diff==Path('/inputs/diff.patch').read_bytes(),'GIT_DIFF_CHANGED')
    git('commit','--no-verify','--no-gpg-sign','--cleanup=verbatim','-F','/inputs/commit-message.txt')
    # Independent state readback after commit. No retry/update-ref after ACK loss.
    require(git('rev-parse','HEAD').decode().strip()==plan['commit_sha']
        and git('rev-parse','HEAD^{tree}').decode().strip()==plan['tree_sha']
        and git('status','--porcelain=v1','--untracked-files=all')==b''
        and git('branch','--show-current').decode().strip()==plan['branch'],'GIT_COMMIT_READBACK_CHANGED')
    require(not git('remote') and identity==(root.stat().st_dev,root.stat().st_ino),'GIT_REMOTE_OR_ROOT_CHANGED')
    inspect_tree(root)
    artifacts=Path('/artifacts')
    for name,pin in plan['files'].items():
        p=root/name;s=p.lstat();data=p.read_bytes()
        require(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and sha(data)==pin['sha256'],'GIT_FILE_READBACK_CHANGED')
        (artifacts/name).write_bytes(data)
    (artifacts/'diff.patch').write_bytes(diff)
    (artifacts/'result.json').write_bytes(canonical({'schema':'aioa.local-git-result.v3',
        'plan_digest':sha(plan_raw),'branch':plan['branch'],'head':plan['commit_sha'],'tree':plan['tree_sha'],
        'status':'CLEAN','files':plan['files'],'source_receipt_sha256':plan['source_receipt_sha256'],
        'diff_sha256':plan['diff_sha256'],'remote_write_performed':False}))


if __name__=='__main__':main()
