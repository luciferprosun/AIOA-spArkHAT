"""Untrusted documentation HTML to bounded text, safe links and SHADOW tags."""
from __future__ import annotations
from html.parser import HTMLParser
import hashlib
import re
from urllib.parse import urljoin
from .policy import AdmissionError,OFFICIAL_HOSTS,canonical_url

class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title=[]
        self.body=[]
        self.links=[]
        self.hidden=0
        self.in_title=False
        self.chars=0
    def handle_starttag(self,tag,attrs):
        if tag in {"script","style","svg","noscript","iframe"}:
            self.hidden+=1
        if tag=="title":
            self.in_title=True
        if tag=="a":
            href=dict(attrs).get("href","")
            if isinstance(href,str):
                self.links.append(href)
    def handle_endtag(self,tag):
        if tag in {"script","style","svg","noscript","iframe"}:
            self.hidden=max(0,self.hidden-1)
        if tag=="title":
            self.in_title=False
    def handle_data(self,data):
        if self.hidden or not data.strip():
            return
        if self.in_title:
            self.title.append(data)
        if self.chars<40000:
            self.body.append(data[:40000-self.chars])
            self.chars+=len(data)

TAGS={
    "html":r"\bhtml\b","css":r"\bcss\b","javascript":r"\bjavascript\b",
    "typescript":r"\btypescript\b","flutter":r"\bflutter\b","react":r"\breact\b",
    "accessibility":r"\b(accessibility|wcag|a11y)\b",
    "security":r"\b(security|csrf|csp|xss)\b",
    "web-api":r"\b(api|fetch|http)\b",
    "performance":r"\b(performance|latency)\b",
    "python":r"\bpython\b","nebius":r"\bnebius\b"
}
def tag_text(text:str)->list[str]:
    return [k for k,v in TAGS.items() if re.search(v,text,re.I)][:8]

def extract(url:str,html:str,*,hosts:frozenset[str]=OFFICIAL_HOSTS)->dict:
    parser=_Parser()
    parser.feed(html[:200000])
    body=re.sub(r"\s+"," "," ".join(parser.body)).strip()[:20000]
    links=[]
    for candidate in parser.links[:500]:
        if len(links)>=30:
            break
        try:
            link=canonical_url(urljoin(url,candidate),hosts)
        except (AdmissionError,ValueError):
            continue
        if link!=url and link not in links:
            links.append(link)
    return {
        "title":re.sub(r"\s+"," "," ".join(parser.title)).strip()[:200] or "Untitled",
        "text":body,"links":links,"tags":tag_text(body),
        "sha256":hashlib.sha256(body.encode("utf-8")).hexdigest()
    }
