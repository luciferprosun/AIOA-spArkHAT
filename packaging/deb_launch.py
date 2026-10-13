"""Thin isolated entry to the existing runtime; diagnostic candidate only."""
import importlib,json,platform,sys
from pathlib import Path

root=Path(__file__).resolve().parent
app=root/'app'
if not sys.flags.isolated or not sys.flags.no_site or sys.version_info[:2]!=(3,12) or platform.machine()!='x86_64':
    raise SystemExit('SUPPORTED_CANDIDATE_ABI_REQUIRED')
sys.path.insert(0,str(app))
metadata=json.loads((root/'candidate.json').read_text())
args=sys.argv[1:]
if args==['--version']:
    print(json.dumps({'name':'aioa-sparkhat','version':metadata['version'],
        'source_commit':metadata['source_commit'],'source_tree':metadata['source_tree'],
        'acceptance':'PASS_LOCAL_LIMITED_CANDIDATE','supported_platforms':[]}))
elif args==['--import-check']:
    names=('runtime.cli','runtime.main','runtime.mission.browser_preview',
           'runtime.mission.operator_console','runtime.mission.sandbox_linux',
           'lab.archaioa.contracts')
    origins={}
    for name in names:
        module=importlib.import_module(name);origin=Path(module.__file__).resolve()
        if not origin.is_relative_to(app):raise SystemExit('PACKAGED_ORIGIN_REQUIRED')
        origins[name]=str(origin)
    for name,module in tuple(sys.modules.items()):
        if (name.startswith(('runtime.','lab.archaioa.')) and getattr(module,'__file__',None)
            and not Path(module.__file__).resolve().is_relative_to(app)):
            raise SystemExit('PACKAGED_ORIGIN_REQUIRED')
    stdlib=Path(sys.base_prefix)/'lib/python3.12'
    archive=Path(sys.base_prefix)/'lib/python312.zip'
    for entry in sys.path:
        location=Path(entry).resolve()
        if not (location.is_relative_to(app) or location.is_relative_to(stdlib) or location==archive):
            raise SystemExit('ISOLATED_IMPORT_PATH_REQUIRED')
    from runtime.main import create_runtime
    runtime=create_runtime(inspection_only=True)
    try:
        status=runtime.operator_status()
        assert status['status']=='UNAVAILABLE' and runtime.executor is None and runtime.provider_manager is None
    finally:runtime.close()
    print(json.dumps({'status':'PASS','origins':origins,'user_site':False,
        'source_checkout_on_import_path':False,'unbound_console':status['status']}))
elif args in ([],['--offline-fixture']):
    from runtime.main import create_runtime
    runtime=create_runtime(inspection_only=True)
    try:status=runtime.operator_status()
    finally:runtime.close()
    fixture=json.loads((root/'offline-fixture.json').read_text())
    print(json.dumps({'mode':'FIXTURE','version':metadata['version'],
        'message':fixture['message'],'task':fixture['task'],'console':status},ensure_ascii=True,indent=2))
elif args and args[0] in ('doctor','console'):
    # Delegate to the original CLI. Neither mode initializes a provider or owner.
    from runtime.cli import main
    main()
else:
    print(json.dumps({'status':'POLICY_BLOCKED','reason':'DIAGNOSTIC_CANDIDATE_ONLY'}))
    raise SystemExit(4)
