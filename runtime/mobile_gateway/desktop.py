"""Checkout-bound launcher for the existing Native host and Chrome console.

No alternative Core, state, identity, paid call or HTTP authority is created.
Explicit desktop invocation can start only a previously initialized profile.
"""
import fcntl
import os
from pathlib import Path
import secrets
import sqlite3
import shlex
import stat
import subprocess
import sys
import time


def prepare_console(root,source,*,client=None):
    from runtime.webapp import mobile_operator_client
    client=client or mobile_operator_client
    result=client(root,{'op':'operator_auth_status'})
    if result.get('ok') is not True:raise ValueError('HOST_UPGRADE_OR_AUTH_READBACK_REQUIRED')
    data=result['data']
    if (data.get('source_sha'),data.get('capsule_digest'))!=tuple(source) or data.get('current_source') is not True:
        raise ValueError('SOURCE_CHANGED_DEPLOYMENT_REQUIRED')
    if data.get('state')=='AUTH_REQUIRED':
        value={'op':'operator_renew','request_id':secrets.token_hex(16),**{k:data[k] for k in
            ('source_sha','capsule_digest','core_instance_id','admission_revision')}}
        result=client(root,value)
        if result.get('ok') is not True or result.get('data',{}).get('state')!='READY':
            raise ValueError('AUTH_REQUIRED_NO_AUTOMATIC_RETRY')
    elif data.get('state')!='READY':raise ValueError('HOST_STATUS_UNKNOWN')
    result=client(root,{'op':'console'})
    if result.get('ok') is not True:raise ValueError('CONSOLE_GRANT_UNKNOWN_NO_AUTOMATIC_RETRY')
    return result['data']


def prepare_chat_session(root,*,client=None):
    """Explicit owner-configured direct chat; no message or provider call."""
    from runtime.webapp import mobile_operator_client
    client=client or mobile_operator_client
    result=client(root,{'op':'chat_session_status'})
    if result.get('ok') is not True:raise ValueError('CHAT_SESSION_READBACK_REQUIRED')
    state=result.get('data',{}).get('state')
    if state=='ACTIVE':return result['data']
    if state!='INACTIVE':raise ValueError('CHAT_SESSION_READBACK_REQUIRED')
    result=client(root,{'op':'chat_session_start','request_id':secrets.token_hex(16),'local_money_limit_usd':None})
    if result.get('ok') is not True or result.get('data',{}).get('state')!='ACTIVE':
        raise ValueError('CHAT_SESSION_START_UNKNOWN_NO_AUTOMATIC_RETRY')
    return result['data']


def _private_root(root):
    root=Path(root).absolute();info=root.lstat()
    if (root.resolve()!=root or not stat.S_ISDIR(info.st_mode)
            or info.st_uid!=os.getuid() or info.st_mode&0o077):raise ValueError('EXISTING_PRIVATE_STATE_REQUIRED')
    return root


def validate_existing_profile(root):
    """Read-only schema/history check, with an exact file identity for startup."""
    root=_private_root(root);path=root/'core-records.sqlite3'
    try:info=path.lstat()
    except OSError:raise ValueError('EXISTING_NATIVE_HISTORY_REQUIRED') from None
    if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1
            or info.st_mode&0o077 or not 4096<=info.st_size<=32*1024*1024):raise ValueError('EXISTING_NATIVE_HISTORY_REQUIRED')
    try:
        with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2) as db:
            db.execute('PRAGMA trusted_schema=OFF')
            if db.execute('PRAGMA quick_check').fetchone()!=('ok',):raise ValueError('EXISTING_NATIVE_HISTORY_REQUIRED')
            columns={row[1] for row in db.execute('PRAGMA table_info(core_records_v1)')}
            if columns!={'scope_key','kind','record_id','revision','record_json','record_digest'}:
                raise ValueError('EXISTING_NATIVE_HISTORY_REQUIRED')
            from runtime.core_admission import OwnerScope
            from runtime.memory_patch.contracts.serialization import canonical_json_bytes
            scope=canonical_json_bytes(OwnerScope('local-linux',f'uid-{os.getuid()}','aioa-main','mobile-status').binding()).decode()
            for kind in ('audit','outbox'):
                if not db.execute('SELECT 1 FROM core_records_v1 WHERE scope_key=? AND kind=? LIMIT 1',(scope,kind)).fetchone():
                    raise ValueError('EXISTING_NATIVE_HISTORY_REQUIRED')
            if not db.execute("SELECT 1 FROM core_records_v1 WHERE scope_key=? AND kind='operation' "
                    "AND record_id GLOB 'mobile-operator-*' AND json_extract(record_json,'$.payload.state')='MOBILE_OPERATOR_ADMISSION' LIMIT 1",(scope,)).fetchone():
                raise ValueError('EXISTING_NATIVE_HISTORY_REQUIRED')
    except sqlite3.Error:raise ValueError('EXISTING_NATIVE_HISTORY_REQUIRED') from None
    after=path.lstat()
    snapshot=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns)
    if snapshot(info)!=snapshot(after):raise ValueError('EXISTING_NATIVE_HISTORY_CHANGED')
    signing_key_identity(root)
    return snapshot(after)


def signing_key_identity(root):
    """Private metadata only; existing-profile startup cannot rotate identity."""
    path=_private_root(root)/'host-signing-key.pem'
    try:info=path.lstat()
    except OSError:raise ValueError('EXISTING_HOST_IDENTITY_REQUIRED') from None
    if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1
            or info.st_mode&0o077 or not 1<=info.st_size<=1024):raise ValueError('EXISTING_HOST_IDENTITY_REQUIRED')
    return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns


def start_existing_profile(args):
    """Explicit start only; never initialize an empty or alternate Core store."""
    from runtime.meta_hackathon.runtime_adapter import ROOT
    root=_private_root(args.state_dir)
    validate_existing_profile(root)
    for name in ('core-records.sqlite3','host-signing-key.pem','runtime.lock'):
        info=(root/name).lstat() if (root/name).exists() else None
        if (info is None or not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid()
                or info.st_nlink!=1 or info.st_mode&0o077):raise ValueError('EXISTING_NATIVE_PROFILE_REQUIRED')
    if (args.host!='127.0.0.1' or args.port!=4317 or not args.mobile_origin
            or not args.mobile_tls_certificate or not args.mobile_tls_key):raise ValueError('EXACT_NATIVE_CONFIGURATION_REQUIRED')
    # Check the original runtime lease. A process awaiting TLS/socket startup
    # must not cause a second PolicyKit prompt or a competing Native process.
    fd=os.open(root/'runtime.lock',os.O_RDWR|os.O_NOFOLLOW)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise ValueError('HOST_ALREADY_RUNNING_WAIT_FOR_READBACK') from None
        fcntl.flock(fd,fcntl.LOCK_UN)
    finally:os.close(fd)
    command=[sys.executable,'-u','-B','-m','runtime.webapp','--mobile-native','--mobile-existing-profile','--state-dir',str(root),
        '--mobile-origin',args.mobile_origin,'--mobile-tls-certificate',args.mobile_tls_certificate,
        '--mobile-tls-key',args.mobile_tls_key,'--host','127.0.0.1','--port','4317']
    if args.mobile_chat:command.append('--mobile-chat')
    log=os.open(root/'desktop-host.log',os.O_WRONLY|os.O_APPEND|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        info=os.fstat(log)
        if info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1 or not stat.S_ISREG(info.st_mode):
            raise ValueError('PRIVATE_LOG_REQUIRED')
        return subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    finally:os.close(log)


def open_desktop(args):
    from runtime.meta_hackathon.runtime_adapter import current_source
    from runtime.webapp import mobile_operator_client,_open_mobile_console
    root=_private_root(args.state_dir);source=current_source()
    # Only absence/refused connection means OFFLINE. A timeout, unknown ACK or
    # denial must never be interpreted as permission to start another host.
    try:data=prepare_console(root,source)
    except (FileNotFoundError,ConnectionRefusedError):
        lock=os.open(root/'desktop-launch.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            info=os.fstat(lock)
            if info.st_uid!=os.getuid() or info.st_mode&0o077 or info.st_nlink!=1:raise ValueError('PRIVATE_LAUNCH_LOCK_REQUIRED')
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:raise ValueError('DESKTOP_START_ALREADY_PENDING') from None
            child=start_existing_profile(args);deadline=time.monotonic()+150
            while time.monotonic()<deadline:
                if child.poll() is not None:raise ValueError('NATIVE_START_FAILED_CHECK_PRIVATE_LOG')
                try:
                    result=mobile_operator_client(root,{'op':'operator_auth_status'})
                    if result.get('ok') is not True:raise ValueError('NATIVE_START_READBACK_UNKNOWN')
                    break
                except (FileNotFoundError,ConnectionRefusedError):time.sleep(.5)
            else:raise ValueError('NATIVE_START_UNKNOWN_NO_AUTOMATIC_RETRY')
            data=prepare_console(root,source)
        finally:os.close(lock)
    if getattr(args,'mobile_chat_direct',False):prepare_chat_session(root)
    _open_mobile_console(data)


def launcher_files(checkout,state_dir,*,origin,direct_chat=False,python_executable=None):
    """Reviewable per-user templates; this function installs nothing."""
    from runtime.mobile_gateway.wire import origin as validate_origin
    validate_origin(origin)
    root=Path(checkout).absolute();state=Path(state_dir).absolute()
    interpreter=str(Path(python_executable or sys.executable).absolute())
    command=[interpreter,'-B','-m','runtime.webapp','--mobile-operator','desktop','--state-dir',str(state),
        '--mobile-origin',origin,'--mobile-chat',
        '--mobile-tls-certificate',str(state/'tls/host.crt'),'--mobile-tls-key',str(state/'tls/host.key'),
        '--host','127.0.0.1','--port','4317']
    if type(direct_chat) is not bool:raise ValueError('DIRECT_CHAT_PREFERENCE_REQUIRED')
    if direct_chat:command.append('--mobile-chat-direct')
    script='#!/bin/sh\n# AIOA verified-checkout desktop launcher v1\nset -eu\ncd -- '+shlex.quote(str(root))+'\nexec '+shlex.join(command)+'\n'
    wrapper=Path.home()/'.local/bin/aioa-mission-control'
    icon=root/'web/white-hole.svg'
    def quoted(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$')+'"'
    entry='[Desktop Entry]\nType=Application\nName=AIOA spArkHAT — White Hole Mission Control\nExec='+quoted(wrapper)+'\nIcon='+str(icon)+'\nTerminal=false\nCategories=Utility;Development;\nStartupNotify=true\n'
    return {'aioa-mission-control':script,'aioa-mission-control.desktop':entry}
