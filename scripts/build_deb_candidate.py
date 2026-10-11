#!/usr/bin/env python3
"""Offline unsigned diagnostic .deb. No installation, download or production signing."""
from __future__ import annotations
import argparse,errno,hashlib,importlib.util,json,os,platform,re,shutil,stat,subprocess,sys
from pathlib import Path,PurePosixPath

VERSION='0.2.0~u12.1'
PRIVATE=PurePosixPath('usr/lib/aioa-sparkhat')/VERSION
EXCLUDED_PARTS=frozenset({'.git','.env','.venv','venv','__pycache__','baseline','archive','archives',
    'knowledge','reports','logs','state','screenshots','obsidian_vault','evidence','node_modules','tests'})
LICENSES=('LICENSE','runtime/nonzero_cloudops/LICENSE-NONZERO.txt',
          'runtime/memory_patch/LICENSE-MEMORY-PATCH.txt')
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
        and not any(part in EXCLUDED_PARTS or part.startswith('.') for part in p.parts),
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
        records.append({'path':name,'bytes':len(raw),'sha256':sha(raw),'license':'MIT','notice':license_path})
    need(all(name in names for name in LICENSES),'LICENSE_CLOSURE_REQUIRED')
    for name in LICENSES:
        notice=regular_bytes(root,name)
        need(notice.startswith(b'MIT License') and b'Permission is hereby granted' in notice
             and b'Copyright' in notice,'LICENSE_CLOSURE_REQUIRED')
    need('runtime/main.py' in names and 'runtime/mission/operator_console.py' in names
         and 'lab/archaioa/contracts.py' in names,'CORE_CLOSURE_REQUIRED')
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
        need(re.fullmatch(r'[0-9A-Za-z.+:~_-]{1,100}',version) is not None
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

def build(root,output):
    root=root.resolve()
    need(sys.platform=='linux' and platform.machine()=='x86_64' and sys.version_info[:2]==(3,12),
         'CANDIDATE_ABI_REQUIRED')
    need(shutil.which('dpkg-deb')=='/usr/bin/dpkg-deb','DPKG_BUILD_REQUIRED')
    need(Path('/bin/sh').resolve()==Path('/usr/bin/dash').resolve(), 'PINNED_LAUNCHER_RUNTIME_REQUIRED')
    need(not subprocess.check_output(['git','status','--porcelain=v1'],cwd=root),'CLEAN_SOURCE_REQUIRED')
    head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    tree=subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=root,text=True).strip()
    epoch=int(subprocess.check_output(['git','show','-s','--format=%ct','HEAD'],cwd=root,text=True))
    names=(root/'packaging/deb_source_allowlist.txt').read_text().splitlines()
    inventory=source_inventory(root,names)
    tracked=set(subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0'))
    need(set(names)<=tracked,'TRACKED_SOURCE_REQUIRED')
    lock=os_lock()
    output=output.absolute()
    need(output.resolve()==output and not output.is_relative_to(root),'DISPOSABLE_OUTPUT_REQUIRED')
    output.mkdir(mode=0o700,parents=True,exist_ok=False)
    stage=output/'stage';stage.mkdir(mode=0o755)
    for item in inventory:
        name=item['path'];raw=regular_bytes(root,name)
        need(sha(raw)==item['sha256'],'SOURCE_CHANGED')
        if name in LICENSES:
            dest=PurePosixPath('usr/share/doc/aioa-sparkhat')/PurePosixPath(name).name
        elif name=='packaging/deb_launch.py':dest=PRIVATE/'launch.py'
        else:dest=PRIVATE/'app'/name
        payload_file(stage,dest,raw)
    metadata={'schema':'aioa.deb-candidate.v1','version':VERSION,'source_commit':head,'source_tree':tree,
        'scope':'LOCAL_DIAGNOSTICS_ONLY','unsigned':True,'browser':'DISABLED_NOT_BUNDLED',
        'target':'Ubuntu24.04/Mint22.x amd64 CPython3.12 CANDIDATE_NOT_SUPPORTED',
        'P0':'PASS_LOCAL_LIMITED_DIAGNOSTIC_CLOSURE','P1':'NOT_ACCEPTED',
        'optional_capabilities':'NonZero/Cockroach/google/Playwright/Textual/U06 execution not packaged as supported modes'}
    payload_file(stage,PRIVATE/'candidate.json',(json.dumps(metadata,sort_keys=True)+'\n').encode())
    fixture={'message':'Local diagnostic candidate. Task execution requires an existing configured Core.',
             'task':'Owned arithmetic example: value = 2 + 3; expected result 5. No effect is executed.'}
    payload_file(stage,PRIVATE/'offline-fixture.json',(json.dumps(fixture)+'\n').encode())
    launcher="""#!/bin/sh
set -eu
package_root=$(CDPATH= cd -- "$(/usr/bin/dirname -- "$0")/../lib/aioa-sparkhat/VERSION_PLACEHOLDER" && pwd -P)
exec /usr/bin/python3.12 -I -S -B "$package_root/launch.py" "$@"
""".replace('VERSION_PLACEHOLDER',VERSION)
    payload_file(stage,'usr/bin/aioa-sparkhat',launcher.encode(),0o755)
    desktop='[Desktop Entry]\nType=Application\nName=AIOA spArkHAT diagnostics\nExec=/usr/bin/aioa-sparkhat --offline-fixture\nIcon=utilities-terminal\nTerminal=true\nCategories=Development;Utility;\n'
    payload_file(stage,'usr/share/applications/aioa-sparkhat.desktop',desktop.encode())
    abi={'python_abi':'cp312','architecture':'amd64','libc_family':'glibc','os_dependencies':lock,
        'launcher_runtime':{'shell':'/bin/sh','shell_provider':'dash','dirname':'/usr/bin/dirname',
            'dirname_provider':'coreutils','interpreter':'/usr/bin/python3.12',
            'binary_sha256':{p:sha(Path(p).read_bytes()) for p in
                ('/usr/bin/dash','/usr/bin/dirname','/usr/bin/python3.12')}},
        'private_app_path':'/'+str(PRIVATE),'third_party_python_bundled':[],
        'excluded_capabilities':['browser','LIVE providers','NonZero extra','Cockroach extra','TUI extra','U06 execution'],
        'media_inventory':[],'media_policy':'No PDF/image/font/audio/video bundled; desktop uses existing system icon'}
    for filename,data in (('SOURCE_ALLOWLIST.json',inventory),('DEPENDENCY_ABI.json',abi)):
        payload_file(stage,PurePosixPath('usr/share/doc/aioa-sparkhat')/filename,(json.dumps(data,indent=2)+'\n').encode())
    sbom={'bomFormat':'CycloneDX','specVersion':'1.5','version':1,
        'metadata':{'component':{'type':'application','name':'aioa-sparkhat','version':VERSION}},
        'components':[{'type':'library','name':p['name'],'version':p['version'],
                       'properties':[{'name':'delivery','value':'OS_PROVIDED_NOT_BUNDLED'}]} for p in lock],
        'properties':[{'name':'status','value':'DRAFT_DIAGNOSTIC_CANDIDATE_NOT_RELEASE_SBOM'}]}
    payload_file(stage,'usr/share/doc/aioa-sparkhat/SBOM_DRAFT.cdx.json',(json.dumps(sbom,indent=2)+'\n').encode())
    control='Package: aioa-sparkhat\nVersion: '+VERSION+'\nArchitecture: amd64\nMaintainer: AIOA spArkHAT local candidate <noreply@example.invalid>\nSection: devel\nPriority: optional\nDepends: '+', '.join(p['name']+' (= '+p['version']+')' for p in lock)+'\nDescription: AIOA spArkHAT local diagnostic candidate\n Unsigned limited offline diagnostic payload. Full desktop workflow not accepted.\n'
    (stage/'DEBIAN').mkdir(mode=0o755);(stage/'DEBIAN/control').write_text(control);(stage/'DEBIAN/control').chmod(0o644)
    for directory in stage.rglob('*'):
        if directory.is_dir():directory.chmod(0o755)
        os.utime(directory,(epoch,epoch),follow_symlinks=False)
    os.utime(stage,(epoch,epoch))
    artifact=output/('aioa-sparkhat_'+VERSION+'_amd64.deb')
    subprocess.run(['/usr/bin/dpkg-deb','--build','--root-owner-group','--uniform-compression','-z6',stage,artifact],
        check=True,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','SOURCE_DATE_EPOCH':str(epoch)},timeout=120)
    files={str(p.relative_to(stage)):sha(p.read_bytes()) for p in sorted(stage.rglob('*')) if p.is_file()}
    result={'schema':'aioa.deb-build.v1','status':'BUILT_UNSIGNED_CANDIDATE','source_commit':head,'source_tree':tree,
        'artifact':str(artifact),'artifact_sha256':sha(artifact.read_bytes()),'artifact_bytes':artifact.stat().st_size,
        'payload_bytes':sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()),'payload_sha256':files,
        'source_inventory':inventory,'abi':abi,'system_installs':0,'production_signing':0,'P1':'NOT_ACCEPTED'}
    (output/'BUILD_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    (output/'SHA_LIST.txt').write_text('\n'.join([result['artifact_sha256'],*files.values()])+'\n')
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=build(args.source,args.output)
    print(json.dumps({k:v for k,v in result.items() if k not in ('payload_sha256','source_inventory','abi')}))
if __name__=='__main__':main()
