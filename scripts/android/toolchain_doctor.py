"""Read-only JSON/human doctor; no binaries execute until their hashes verify."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

if __package__:
    from . import toolchain_lib as lib
    from . import installer
else:
    import toolchain_lib as lib
    import installer


def report(require_installed=False):
    facts=lib.probe_storage();gate=lib.storage_decision(facts,lib.load_qualification())
    value={'schema':'aioa.android.doctor.v1','status':gate['status'],'storage':gate,
        'mount_identity_matches':all(facts.get(k)==v for k,v in {'target':str(lib.MOUNT),'device':lib.DEVICE,'uuid':lib.UUID,'fstype':'ext4'}.items()),
        'space_bytes':{'external':facts['external_free'],'root':facts['root_free']},
        'planned_versions':installer.catalog()['versions'],
        'path_commands':{name:bool(shutil.which(name)) for name in ('java','javac','gradle','sdkmanager','shellcheck')},
        'installed':'NOT_INSPECTED_STORAGE_BLOCKED','source_sha':lib.git('rev-parse','HEAD'),
        'source_clean':not bool(lib.git('status','--porcelain','-uall')),
        'sdk_license_observed':False,'license_acceptance_performed':False,'downloads':0}
    pins=(lib.REPO/'clients/android/gradle/wrapper/gradle-wrapper.properties').read_text()
    lock=installer.catalog()
    value['project_pins_match']=('gradle-8.13-bin.zip' in pins
        and lock['artifacts'][1]['sha256'] in pins
        and lib.sha(lib.REPO/'clients/android/gradle/wrapper/gradle-wrapper.jar')==lock['wrapper_sha256'])
    required=json.loads((lib.REPO/'clients/android/ANDROID_BUILD_INPUT_MANIFEST.json').read_text())['required_toolchain']
    mapping={'jdk_major':'jdk','gradle':'gradle','agp':'android_gradle_plugin','kotlin':'kotlin','compile_sdk':'compile_sdk','build_tools':'build_tools'}
    value['project_pins_match']=value['project_pins_match'] and all(lock['versions'][k]==required[v] for k,v in mapping.items())
    if gate['may_stage']:
        value['sdk_license_observed']=lib.license_observed(lib.ROOT/'sdk')
        if require_installed:
            try:
                for artifact in lock['artifacts']:installer.component_check(artifact)
                value['installed']='HASH_VERIFIED_NOT_EXECUTED';value['status']='INSTALLED_HASHES_MATCH'
            except (lib.Blocked,OSError,ValueError,KeyError):value['status']='BLOCKED_TOOLCHAIN';value['installed']='MISSING_OR_DRIFT'
    if not value['project_pins_match']:value['status']='BLOCKED_PROJECT_PIN_DRIFT'
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json',action='store_true');parser.add_argument('--require-installed',action='store_true')
    args=parser.parse_args()
    try:value=report(args.require_installed)
    except (lib.Blocked,OSError,ValueError,KeyError):value={'status':'BLOCKED_PREFLIGHT_UNKNOWN'}
    if args.json:print(json.dumps(value,sort_keys=True,indent=2))
    else:
        print('AIOA Android toolchain: '+value['status'])
        print(json.dumps(value,sort_keys=True,indent=2))
    return 0 if value['status']=='INSTALLED_HASHES_MATCH' else 2


if __name__=='__main__':raise SystemExit(main())
