"""Fail-closed HTTP: verified HTTPS, pinned-public-IP sockets, robots, no redirects."""
from __future__ import annotations
import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from .policy import AdmissionError,DEFAULT_USER_AGENT,OFFICIAL_HOSTS,canonical_url,public_dns

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host:str,ip:str,family:int,*,timeout:float=15):
        super().__init__(host,443,timeout=timeout,context=ssl.create_default_context())
        self.ip=ip
        self.family=family
    def connect(self):
        address=(self.ip,443,0,0) if self.family==socket.AF_INET6 else (self.ip,443)
        raw=socket.socket(self.family,socket.SOCK_STREAM)
        raw.settimeout(self.timeout)
        try:
            raw.connect(address)
            self.sock=self._context.wrap_socket(raw,server_hostname=self.host)
        except BaseException:
            raw.close()
            raise

def request(host:str,path:str,*,method:str="GET",body:bytes|None=None,
            headers:dict[str,str]|None=None,limit:int=120000)->tuple[bytes,str]:
    if host not in OFFICIAL_HOSTS and host not in {"api.studio.nebius.ai","api.tokenfactory.nebius.com","openrouter.ai"}:
        raise AdmissionError("host not allowlisted")
    if not path.startswith("/") or len(path)>1900 or "#" in path or "?" in path:
        raise AdmissionError("unsafe request path")
    ip,family=public_dns(host)
    conn=PinnedHTTPS(host,ip,family)
    try:
        conn.request(method,path,body=body,headers={
            "User-Agent":DEFAULT_USER_AGENT,"Accept-Encoding":"identity",
            "Connection":"close",**(headers or {})
        })
        resp=conn.getresponse()
        if resp.status!=200:
            raise AdmissionError(f"HTTP {resp.status}: redirects/retries forbidden")
        if (resp.getheader("Content-Encoding") or "identity").lower()!="identity":
            raise AdmissionError("compressed responses rejected")
        result=resp.read(limit+1)
        if len(result)>limit:
            raise AdmissionError("response byte quota exceeded")
        content_type=(resp.getheader("Content-Type") or "").lower().split(";")[0].strip()
        return result,content_type
    finally:
        conn.close()

class DocumentFetcher:
    def __init__(self,hosts:frozenset[str]=OFFICIAL_HOSTS,max_bytes:int=120000):
        if not hosts or not hosts.issubset(OFFICIAL_HOSTS):
            raise AdmissionError("invalid official host subset")
        self.hosts=hosts
        self.max_bytes=min(max_bytes,256000)
        self.robots={}
    def read(self,url:str)->str:
        url=canonical_url(url,self.hosts)
        p=urlsplit(url)
        host=p.hostname
        if host not in self.robots:
            rob,kind=request(host,"/robots.txt",headers={"Accept":"text/plain"},limit=64000)
            if kind!="text/plain":
                raise AdmissionError("robots.txt unavailable or not plaintext")
            parser=RobotFileParser()
            parser.parse(rob.decode("utf-8",errors="replace").splitlines())
            self.robots[host]=parser
        if not self.robots[host].can_fetch(DEFAULT_USER_AGENT,url):
            raise AdmissionError("robots.txt disallows this path")
        data,kind=request(host,p.path or "/",headers={
            "Accept":"text/html, text/plain, application/xhtml+xml"
        },limit=self.max_bytes)
        if kind not in {"text/html","text/plain","application/xhtml+xml"}:
            raise AdmissionError("unsupported document MIME; no binaries/private API")
        return data.decode("utf-8",errors="replace")

def model_post(origin:str,path:str,payload:dict,secret:str)->dict:
    p=urlsplit(origin)
    if (p.scheme!="https" or not p.hostname or p.path not in {"","/"} or
        p.port not in {None,443} or p.query or p.fragment or p.username or p.password or
        p.hostname not in {"api.studio.nebius.ai","api.tokenfactory.nebius.com","openrouter.ai"}):
        raise AdmissionError("provider origin not explicitly admitted")
    if path not in {"/v1/chat/completions","/api/v1/chat/completions"}:
        raise AdmissionError("provider route not approved")
    if not secret or any(c.isspace() for c in secret) or len(secret)>4096:
        raise AdmissionError("credential missing or invalid")
    body=json.dumps(payload,separators=(",",":"),ensure_ascii=False).encode()
    if len(body)>32768:
        raise AdmissionError("model request body cap")
    data,kind=request(p.hostname,path,method="POST",body=body,
        headers={"Authorization":"Bearer "+secret,"Content-Type":"application/json",
                 "Accept":"application/json"},limit=65536)
    if kind!="application/json":
        raise AdmissionError("provider non-json response")
    value=json.loads(data)
    if not isinstance(value,dict):
        raise AdmissionError("malformed provider response")
    return value
