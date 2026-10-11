#!/usr/bin/env python3
"""Offline unsigned diagnostic .deb. No installation, download or production signing."""
from __future__ import annotations
import argparse,errno,hashlib,importlib.util,json,os,platform,re,shutil,stat,subprocess,sys
import sysconfig,tomllib
from pathlib import Path,PurePosixPath

_spec=importlib.util.spec_from_file_location('aioa_deb_provenance',Path(__file__).with_name('deb_provenance.py'))
evidence=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(evidence)

VERSION='0.2.0~u13.1'
PRIVATE=PurePosixPath('usr/lib/aioa-sparkhat')/VERSION
EXCLUDED_PARTS=frozenset({'.git','.env','.venv','venv','__pycache__','baseline','archive','archives',
    'knowledge','reports','logs','state','screenshots','obsidian_vault','evidence','node_modules','tests'})
LICENSES=('LICENSE','runtime/nonzero_cloudops/LICENSE-NONZERO.txt',
          'runtime/memory_patch/LICENSE-MEMORY-PATCH.txt')
CORE_STATE_SOURCES=frozenset({'runtime/nonzero_cloudops/state/__init__.py',
    'runtime/nonzero_cloudops/state/files.py'})
OS_PACKAGES=('python3.12','python3.12-minimal','libpython3.12-stdlib','libpython3.12-minimal',
    'libc6','libexpat1','libbz2-1.0','libffi8','liblzma5','libsqlite3-0',
    'libssl3t64','zlib1g','libuuid1','libreadline8t64','libncursesw6','libtinfo6','dash','coreutils')
GITHUB_TOKEN=re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b')

def need(value,code):
    if not value:raise ValueError(code)

def sha(raw):return hashlib.sha256(raw).hexdigest()

def regular_bytes(root,relative):
    need(type(relative) is str and re.fullmatch(r'[A-Za-z0-9_./-]{1,220}',relative) is not None,
         'PACKAGE_PATH_DENIED')
    p=PurePosixPath(relative)
    need(not p.is_absolute() and '..' not in p.parts and str(p)==relative
        and not any((part in EXCLUDED_PARTS and not
                     (part=='state' and relative in CORE_STATE_SOURCES))
                    or part.startswith('.') for part in p.parts),
        'PACKAGE_PATH_DENIED')
    path=root/relative
    need(path.resolve()==root.resolve()/relative,'PACKAGE_SYMLINK_DENIED')
    parent=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in p.parts[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=parent)
            os.close(parent);parent=child
        fd=os.open(p.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
    except OSError as error:
        if error.errno in (errno.ELOOP,errno.ENOTDIR):
            raise ValueError('PACKAGE_SYMLINK_DENIED') from None
        raise
    finally:
        os.close(parent)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        need(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=1048576,
             'PACKAGE_FILE_DENIED')
        raw=stream.read(1048577)
        after=os.fstat(stream.fileno())
        need(len(raw)==info.st_size and
             (info.st_size,info.st_mtime_ns,info.st_ctime_ns,info.st_nlink)==
             (after.st_size,after.st_mtime_ns,after.st_ctime_ns,after.st_nlink),
             'PACKAGE_FILE_CHANGED')
    return raw

def source_inventory(root,names):
    need(type(names) is list and names==sorted(set(names)) and len(names)>0,'SOURCE_ALLOWLIST')
    scanner_path=root/'scripts/check_changed_secrets.py'
    spec=importlib.util.spec_from_file_location('unchanged_secret_scanner',scanner_path)
    scanner=importlib.util.module_from_spec(spec);spec.loader.exec_module(scanner)
    records=[]
    for name in names:
        need(name in LICENSES or name=='packaging/deb_launch.py' or
             (name.startswith(('runtime/','lab/archaioa/')) and name.endswith('.py')
               and not name.endswith('/fixture.py') and name not in
                   ('runtime/tools/web_reader.py','runtime/tools/build_rhcsa_library.py'))
              or name in ('runtime/prompts/system_prompt.txt','runtime/adaptive_routing/routing_modes.json','runtime/adaptive_routing/aoia_config.json','runtime/adaptive_routing/environment/traffic_profiles.json')
              or (name.startswith('runtime/mission/native/') and name.endswith('.c'))
              or (name.startswith('runtime/memory_patch/sql/') and name.endswith(('.sql','.json'))),
             'SOURCE_NOT_IN_POLICY')
        raw=regular_bytes(root,name)
        text=raw.decode('utf-8',errors='strict')
        need(not scanner.scan_text(text) and GITHUB_TOKEN.search(text) is None,'PACKAGE_SECRET_DENIED')
        license_path='runtime/memory_patch/LICENSE-MEMORY-PATCH.txt' if name.startswith('runtime/memory_patch/') else 'runtime/nonzero_cloudops/LICENSE-NONZERO.txt' if name.startswith('runtime/nonzero_cloudops/') else 'LICENSE'
        records.append({'path':name,'bytes':len(raw),'sha256':sha(raw),
                        'sha1':hashlib.sha1(raw).hexdigest(),'license':'MIT','notice':license_path})
    need(all(name in names for name in LICENSES),'LICENSE_CLOSURE_REQUIRED')
    for name in LICENSES:
        notice=regular_bytes(root,name)
        need(notice.startswith(b'MIT License') and b'Permission is hereby granted' in notice
             and b'Copyright' in notice,'LICENSE_CLOSURE_REQUIRED')
    need('runtime/main.py' in names and 'runtime/mission/operator_console.py' in names
         and 'lab/archaioa/contracts.py' in names and CORE_STATE_SOURCES<=set(names),
         'CORE_CLOSURE_REQUIRED')
    return records

def os_lock():
    records={};pending=list(OS_PACKAGES)
    def query(package):
        need(re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?',package) is not None,
             'ABI_DEPENDENCY_REQUIRED')
        result=subprocess.run(['/usr/bin/dpkg-query','-W',
            '-f=${Package}\t${Version}\t${Architecture}\t${Depends}\t${Pre-Depends}\t${Status}',package],
            capture_output=True,text=True,timeout=10)
        if result.returncode:return None
        fields=result.stdout.split('\t')
        if len(fields)!=6 or fields[5]!='install ok installed':return None
        name,version,arch,depends,predepends,_=fields
        need(re.fullmatch(r'[0-9][0-9A-Za-z.+:~_-]{0,99}',version) is not None
             and arch in ('amd64','all'),'ABI_DEPENDENCY_REQUIRED')
        return {'name':name,'version':version,'architecture':arch,
                'declared_dependencies':depends,'declared_predependencies':predepends,
                'delivery':'OS_PROVIDED_NOT_BUNDLED'}
    while pending:
        package=pending.pop()
        if package in records:continue
        record=query(package);need(record is not None,'OS_DEPENDENCY_CLOSURE_UNKNOWN')
        records[package]=record
        for group in filter(None,(record['declared_dependencies']+','+record['declared_predependencies']).split(',')):
            candidates=[]
            for alternative in group.split('|'):
                name=alternative.strip().split()[0].removesuffix(':any').removesuffix(':native')
                if query(name) is not None:candidates.append(name)
            need(bool(candidates),'OS_DEPENDENCY_CLOSURE_UNKNOWN')
            pending.append(candidates[0])
    return [records[name] for name in sorted(records)]

def payload_file(stage,path,data,mode=0o644):
    target=stage/str(path);target.parent.mkdir(parents=True,exist_ok=True,mode=0o755)
    need(not target.exists() and not target.is_symlink(),'PAYLOAD_ALREADY_EXISTS')
    target.write_bytes(data);target.chmod(mode)

def prepare_context(root,expected_commit=None,expected_tree=None):
    root=Path(root).absolute()
    need(root==root.resolve(),'SOURCE_PATH_REQUIRED')
    need(sys.platform=='linux' and platform.machine()=='x86_64' and sys.version_info[:2]==(3,12),
         'CANDIDATE_ABI_REQUIRED')
    need(shutil.which('dpkg-deb')=='/usr/bin/dpkg-deb','DPKG_BUILD_REQUIRED')
    need(Path('/bin/sh').resolve()==Path('/usr/bin/dash').resolve(), 'PINNED_LAUNCHER_RUNTIME_REQUIRED')
    need(not evidence.git(root,'status','--porcelain=v1','--untracked-files=all'),'CLEAN_SOURCE_REQUIRED')
    head=evidence.git(root,'rev-parse','HEAD').decode().strip()
    tree=evidence.git(root,'rev-parse','HEAD^{tree}').decode().strip()
    names=regular_bytes(root,'packaging/deb_source_allowlist.txt').decode().splitlines()
    source=evidence.pin_source(root,expected_commit or head,expected_tree or tree,
                               [*names,*evidence.BUILD_INPUTS],regular_bytes)
    project=tomllib.loads(regular_bytes(root,'pyproject.toml').decode())['project']
    evidence.validate_version(VERSION,project['name'],project['version'])
    inventory=source_inventory(root,names)
    lock=os_lock()
    evidence.validate_lock(lock)
    tool_owners={'/usr/bin/dash':'dash','/usr/bin/dirname':'coreutils',
        '/usr/bin/dpkg-deb':'dpkg','/usr/bin/dpkg-query':'dpkg','/usr/bin/git':'git',
        '/usr/bin/python3.12':'python3.12-minimal','/usr/bin/xz':'xz-utils'}
    toolchain=[];tool_packages={}
    for path,owner in sorted(tool_owners.items()):
        raw=evidence.safe_bytes(Path(path),16*1024*1024)
        query=subprocess.run(['/usr/bin/dpkg-query','-W','-f=${Version}\t${Architecture}\t${Status}',owner],
            check=True,capture_output=True,text=True,timeout=10,env=evidence.GIT_ENV)
        version,arch,status=query.stdout.split('\t')
        need(status=='install ok installed','TOOLCHAIN_REQUIRED')
        tool_packages[owner]={'name':owner,'version':version,'architecture':arch,
            'delivery':'OS_PROVIDED_NOT_BUNDLED','declared_dependencies':'','declared_predependencies':''}
        toolchain.append({'name':Path(path).name,'path':path,'package':owner,
            'version':version,'sha256':sha(raw),'license_evidence':'/usr/share/doc/'+owner+'/copyright'})
    notice_lock={p['name']:p for p in lock};notice_lock.update(tool_packages)
    notices=evidence.dependency_notices([notice_lock[n] for n in sorted(notice_lock)])
    notice_hash={n['name']:n['sha256'] for n in notices}
    for tool in toolchain:tool['license_evidence_sha256']=notice_hash[tool['package']]
    abi={'python_abi':'cp312','python_version':platform.python_version(),
        'python_soabi':sysconfig.get_config_var('SOABI'),'architecture':'amd64','libc_family':'glibc','os_dependencies':lock,
        'launcher_runtime':{'shell':'/bin/sh','shell_provider':'dash','dirname':'/usr/bin/dirname',
            'dirname_provider':'coreutils','interpreter':'/usr/bin/python3.12',
            'binary_sha256':{t['path']:t['sha256'] for t in toolchain if t['path'] in
                ('/usr/bin/dash','/usr/bin/dirname','/usr/bin/python3.12')}},
        'private_app_path':'/'+str(PRIVATE),'third_party_python_bundled':[],
        'excluded_capabilities':['browser','LIVE providers','NonZero extra','Cockroach extra','TUI extra','U06 execution'],
        'media_inventory':[],'media_policy':'No PDF/image/font/audio/video bundled; desktop uses existing system icon'}
    return {'version':VERSION,'source':source,'source_inventory':inventory,
            'abi':abi,'notices':notices,'toolchain':toolchain}

def candidate_payload(root,context):
    inventory=context['source_inventory'];source=context['source'];files={}
    def put(path,raw,mode=0o644):
        name=str(path);need(name not in files,'PAYLOAD_ALREADY_EXISTS');files[name]=(raw,mode)
    for item in inventory:
        name=item['path'];raw=regular_bytes(root,name)
        need(sha(raw)==item['sha256'],'SOURCE_CHANGED')
        if name in LICENSES:
            dest=PurePosixPath('usr/share/doc/aioa-sparkhat')/PurePosixPath(name).name
        elif name=='packaging/deb_launch.py':dest=PRIVATE/'launch.py'
        else:dest=PRIVATE/'app'/name
        put(dest,raw)
    metadata={'schema':'aioa.deb-candidate.v1','version':VERSION,'source_commit':source['commit'],'source_tree':source['tree'],
        'scope':'LOCAL_DIAGNOSTICS_ONLY','unsigned':True,'browser':'DISABLED_NOT_BUNDLED',
        'target':'Ubuntu24.04/Mint22.x amd64 CPython3.12 CANDIDATE_NOT_SUPPORTED',
        'P0':'PASS_LOCAL_LIMITED_DIAGNOSTIC_CLOSURE','P1':'NOT_ACCEPTED',
        'optional_capabilities':'NonZero/Cockroach/google/Playwright/Textual/U06 execution not packaged as supported modes'}
    put(PRIVATE/'candidate.json',evidence.canonical_json(metadata))
    fixture={'message':'Local diagnostic candidate. Task execution requires an existing configured Core.',
             'task':'Owned arithmetic example: value = 2 + 3; expected result 5. No effect is executed.'}
    put(PRIVATE/'offline-fixture.json',evidence.canonical_json(fixture))
    launcher="""#!/bin/sh
set -eu
package_root=$(CDPATH= cd -- "$(/usr/bin/dirname -- "$0")/../lib/aioa-sparkhat/VERSION_PLACEHOLDER" && pwd -P)
exec /usr/bin/python3.12 -I -S -B "$package_root/launch.py" "$@"
""".replace('VERSION_PLACEHOLDER',VERSION)
    put('usr/bin/aioa-sparkhat',launcher.encode(),0o755)
    desktop='[Desktop Entry]\nType=Application\nName=AIOA spArkHAT diagnostics\nExec=/usr/bin/aioa-sparkhat --offline-fixture\nIcon=utilities-terminal\nTerminal=true\nCategories=Development;Utility;\n'
    put('usr/share/applications/aioa-sparkhat.desktop',desktop.encode())
    source_provenance={'schema':'aioa.deb-source.v1','version':VERSION,'source':source,
        'toolchain':context['toolchain'],'python_abi':'cp312','architecture':'amd64','unsigned':True,
        'scope':'LOCAL_DIAGNOSTICS_ONLY','artifact_sbom':'EXTERNAL SBOM.spdx.json binds final package SHA256',
        'release_gate':'BLOCKED_OR_PENDING','clean_host_certification':'ABSENT','signer':'ABSENT'}
    notice_manifest=[{k:v for k,v in n.items() if k!='text'} for n in context['notices']]
    for filename,data in (('SOURCE_ALLOWLIST.json',inventory),('DEPENDENCY_ABI.json',context['abi']),
            ('SOURCE_PROVENANCE.json',source_provenance),('DEPENDENCY_LICENSE_EVIDENCE.json',notice_manifest)):
        put(PurePosixPath('usr/share/doc/aioa-sparkhat')/filename,evidence.canonical_json(data))
    for notice in context['notices']:
        put(PurePosixPath('usr/share/doc/aioa-sparkhat/os-notices')/(notice['name']+'.copyright'),notice['text'].encode())
    spec=importlib.util.spec_from_file_location('verified_payload_scanner',root/'scripts/check_changed_secrets.py')
    scanner=importlib.util.module_from_spec(spec);spec.loader.exec_module(scanner)
    for raw,_ in files.values():
        text=raw.decode('utf-8','strict')
        need(not scanner.scan_text(text) and GITHUB_TOKEN.search(text) is None,'PACKAGE_SECRET_DENIED')
    lock=context['abi']['os_dependencies']
    control='Package: aioa-sparkhat\nVersion: '+VERSION+'\nArchitecture: amd64\nMaintainer: AIOA spArkHAT local candidate <noreply@example.invalid>\nSection: devel\nPriority: optional\nDepends: '+', '.join(p['name']+' (= '+p['version']+')' for p in lock)+'\nDescription: AIOA spArkHAT local diagnostic candidate\n Unsigned limited offline diagnostic payload. Full desktop workflow not accepted.\n'
    return files,control.encode()

def build(root,output,*,expected_commit=None,expected_tree=None):
    context=prepare_context(root,expected_commit,expected_tree)
    root=Path(root).absolute();source=context['source'];epoch=source['epoch']
    files,control=candidate_payload(root,context)
    output=output.absolute()
    need(output.resolve()==output and not output.is_relative_to(root),'DISPOSABLE_OUTPUT_REQUIRED')
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    stage=output/'stage';stage.mkdir(mode=0o755)
    for name,(raw,mode) in files.items():payload_file(stage,name,raw,mode)
    payload_file(stage,'DEBIAN/control',control)
    for directory in stage.rglob('*'):
        if directory.is_dir():directory.chmod(0o755)
        os.utime(directory,(epoch,epoch),follow_symlinks=False)
    os.utime(stage,(epoch,epoch))
    artifact=output/('aioa-sparkhat_'+VERSION+'_amd64.deb')
    subprocess.run(['/usr/bin/dpkg-deb','--build','--root-owner-group','--uniform-compression','--threads-max=1','-Zxz','-z6',stage,artifact],
        check=True,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','SOURCE_DATE_EPOCH':str(epoch)},timeout=120)
    need(context==prepare_context(root,source['commit'],source['tree']),'BUILD_SOURCE_OR_TOOLCHAIN_DRIFT')
    raw=evidence.safe_bytes(artifact,evidence.MAX_DEB_BYTES);digest=sha(raw)
    evidence.verify_contents(evidence.read_deb(raw,expected_sha256=digest),files,control,epoch)
    sbom=evidence.canonical_json(evidence.spdx_sbom(context,digest))
    provenance=evidence.canonical_json(evidence.provenance(context,digest,sha(sbom),len(raw)))
    (output/'SBOM.spdx.json').write_bytes(sbom);(output/'PROVENANCE.json').write_bytes(provenance)
    hashes={name:sha(raw) for name,(raw,_) in sorted(files.items())}
    result={'schema':'aioa.deb-build.v2','status':'BUILT_VERIFIED_UNSIGNED_DIAGNOSTIC','source_commit':source['commit'],
        'source_tree':source['tree'],'artifact':str(artifact),'artifact_sha256':digest,'artifact_bytes':len(raw),
        'payload_bytes':sum(len(raw) for raw,_ in files.values()),'payload_sha256':hashes,
        'source_inventory':context['source_inventory'],'abi':context['abi'],'toolchain':context['toolchain'],
        'sbom_sha256':sha(sbom),'provenance_sha256':sha(provenance),
        'system_installs':0,'production_signing':0,'P1':'NOT_ACCEPTED','P3':'NOT_ACCEPTED'}
    (output/'BUILD_RESULT.json').write_bytes(evidence.canonical_json(result))
    (output/'SHA_LIST.txt').write_text('\n'.join([digest,sha(sbom),sha(provenance),*hashes.values()])+'\n')
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--expected-commit',required=True);parser.add_argument('--expected-tree',required=True)
    args=parser.parse_args();result=build(args.source,args.output,expected_commit=args.expected_commit,expected_tree=args.expected_tree)
    print(json.dumps({k:v for k,v in result.items() if k not in ('payload_sha256','source_inventory','abi','toolchain')}))
if __name__=='__main__':main()
