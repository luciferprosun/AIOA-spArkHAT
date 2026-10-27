"""Strict source and local sandbox admission. No Core/USB writes."""
from __future__ import annotations
import ipaddress
import os
from pathlib import Path
import posixpath
import re
import socket
from urllib.parse import unquote, urlsplit, urlunsplit

class AdmissionError(ValueError):
    pass

OFFICIAL_HOSTS=frozenset({
    "developer.mozilla.org","www.w3.org","web.dev","react.dev",
    "docs.python.org","www.typescriptlang.org","docs.nebius.com",
    "docs.flutter.dev","docs.github.com","html.spec.whatwg.org"
})
DEFAULT_USER_AGENT="AIOA-Nemotron48-Research/0.1 (+bounded-owner-operated)"

def canonical_url(url:str,hosts:frozenset[str]=OFFICIAL_HOSTS)->str:
    if not isinstance(url,str) or len(url)>1800 or any(ord(c)<33 for c in url):
        raise AdmissionError("invalid URL")
    try:
        p=urlsplit(url)
        host=p.hostname
        port=p.port
    except ValueError as e:
        raise AdmissionError("invalid URL authority") from e
    if p.scheme!="https" or not host or port not in (None,443):
        raise AdmissionError("only HTTPS default port allowed")
    if p.username is not None or p.password is not None or p.query or p.fragment:
        raise AdmissionError("URL credential/query/fragment forbidden")
    if host.lower() not in hosts or p.netloc.lower() not in {host.lower(),host.lower()+":443"}:
        raise AdmissionError("host outside official documentation allowlist")
    try:
        ipaddress.ip_address(host)
        raise AdmissionError("IP literal forbidden")
    except ValueError:
        pass
    path=p.path or "/"
    if "\\" in path or any(x in {".",".."} for x in unquote(path).split("/")):
        raise AdmissionError("traversal path forbidden")
    if any(ord(c)<32 for c in unquote(path)):
        raise AdmissionError("control character in URL path")
    return urlunsplit(("https",host.lower(),posixpath.normpath(path) if path!="/" else "/","",""))

def public_dns(host:str,port:int=443)->tuple[str,int]:
    if host not in OFFICIAL_HOSTS and host not in {"api.studio.nebius.ai","api.tokenfactory.nebius.com","openrouter.ai"}:
        raise AdmissionError("DNS lookup outside allowlist")
    try:
        answers=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    except OSError as e:
        raise AdmissionError("DNS lookup failed") from e
    if not answers:
        raise AdmissionError("empty DNS")
    for family,_,_,_,addr in answers:
        if not ipaddress.ip_address(addr[0]).is_global:
            raise AdmissionError("mixed/private/loopback DNS forbidden")
    return answers[0][4][0],answers[0][0]

def safe_state_dir(value:str|Path,*,create:bool=False)->Path:
    path=Path(value)
    if not path.is_absolute() or ".." in path.parts or len(str(path))>512:
        raise AdmissionError("state-dir must be a safe absolute path")
    base=next((root for root in (Path("/var/tmp"),Path("/tmp")) if root in path.parents),None)
    if base is None or len(path.relative_to(base).parts)>3:
        raise AdmissionError("state-dir must be a private subdirectory of /tmp or /var/tmp")
    for ancestor in (path,*path.parents):
        if ancestor.is_symlink() or (ancestor/".git").exists():
            raise AdmissionError("state symlink/Git ancestors forbidden")
    if create:
        path.mkdir(mode=0o700,parents=True,exist_ok=True)
        os.chmod(path,0o700)
    if not path.is_dir():
        raise AdmissionError("state directory not initialized")
    st=path.stat()
    if st.st_uid!=os.getuid() or st.st_mode & 0o077:
        raise AdmissionError("state-dir must be owned by user and 0700")
    if os.statvfs(path).f_flag & getattr(os,"ST_RDONLY",1):
        raise AdmissionError("state-dir filesystem read only")
    return path

def validate_owner(owner:str)->str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,64}",owner or ""):
        raise AdmissionError("opaque owner scope required")
    if owner.lower() in {"root","admin","public","everyone"}:
        raise AdmissionError("privileged/public owner scope forbidden")
    return owner
