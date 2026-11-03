"""Explicit, disjoint APK channel. Public identity only; private signer stays out of Git."""
import base64
import hashlib
import os
import re
import subprocess

if __package__:
    from . import installer, toolchain_lib as lib
else:
    import installer
    import toolchain_lib as lib

CHANNEL='COSMIC4_USB_V1'
SOURCE_REF='refs/heads/feat/cosmic4-usb-20261103'
PACKAGE='eu.sparkhat.aioa.companion.cosmic4'
CERTIFICATE='3aa33eda63d3516010ddbf0fe0ff8de6b6dab6f6fc48088ee2592bde3b627bc4'
VERSION_CODE=400
VERSION_NAME='4.0.0-cosmic'


def validate(channel):
    lib.require(channel in (None, CHANNEL),'BLOCKED_APK_CHANNEL')
    return channel==CHANNEL


def manifest_identity():
    return {'package':PACKAGE,'version_code':VERSION_CODE,'version_name':VERSION_NAME,
        'update_signing_certificate_sha256':CERTIFICATE,
        'variant':'cosmic4','old_package_preserved':True,'old_identity_migrated':False}


def prepare_signer(output,jdk,environment,secrets):
    """Materialize the durable owner key once in an ephemeral private job, never generate."""
    raw=secrets.get('AIOA_COSMIC4_STORE_B64',''); password=secrets.get('AIOA_COSMIC4_PASSWORD','')
    lib.require(type(raw) is str and 0<len(raw)<=65536 and type(password) is str
        and re.fullmatch(r'[A-Za-z0-9_-]{48,128}',password),'BLOCKED_COSMIC4_SIGNER_MISSING')
    try:
        key=base64.b64decode(raw,validate=True)
    except ValueError:raise lib.Blocked('BLOCKED_COSMIC4_SIGNER_ENCODING') from None
    lib.require(base64.b64encode(key).decode()==raw and 1024<=len(key)<=32768,'BLOCKED_COSMIC4_SIGNER_ENCODING')
    paths=[output/n for n in ('debug.keystore','debug-certificate.der','DEBUG_SIGNER.json')]
    lib.require(all(not p.exists() and not p.is_symlink() for p in paths),'BLOCKED_DEBUG_SIGNER_EXISTS')
    fd=os.open(paths[0],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(key)
    scoped={**environment,'AIOA_COSMIC4_PASSWORD':password}
    response=subprocess.run([str(jdk/'bin/keytool'),'-exportcert','-keystore',str(paths[0]),
        '-storetype','PKCS12','-storepass:env','AIOA_COSMIC4_PASSWORD','-alias','cosmic4','-file',str(paths[1])],
        env=scoped,stdin=subprocess.DEVNULL,capture_output=True,timeout=30)
    lib.require(response.returncode==0,'BLOCKED_COSMIC4_SIGNER_CERTIFICATE')
    paths[1].chmod(0o600)
    certificate=lib.private_bytes(paths[1],max_bytes=16384)
    lib.require(hashlib.sha256(certificate).hexdigest()==CERTIFICATE,'BLOCKED_COSMIC4_SIGNER_PIN')
    marker={'schema':'aioa.android.controlled-debug-signer.v1','kind':'DEBUG','apk_channel':CHANNEL,
        'certificate_sha256':CERTIFICATE,'keystore_sha256':hashlib.sha256(key).hexdigest(),
        'old_apk_update_signature_compatibility':'DIFFERENT_PACKAGE_PRESERVED',
        'cosmic4_update_signature_compatibility':'PERSISTENT_OWNER_KEY'}
    installer.private_write(paths[2],marker)
    environment['AIOA_COSMIC4_PASSWORD']=password
    return marker
