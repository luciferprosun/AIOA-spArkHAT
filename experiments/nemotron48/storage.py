"""Private knowledge index, hash-chained receipts, shadow pheromone tags."""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid
from .policy import AdmissionError,safe_state_dir,validate_owner

def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False)
def digest(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()
def atomic_json(path,obj):
    fd,tmp=tempfile.mkstemp(prefix=".pending-",dir=str(path.parent))
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as f:
            f.write((canonical(obj)+"\n").encode())
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

class Store:
    def __init__(self,root,*,create=False):
        self.root=safe_state_dir(root,create=create)
        path=self.root/"knowledge.sqlite3"
        if path.is_symlink() or not create and not path.is_file():
            raise AdmissionError("database absent/symlink")
        self.db=sqlite3.connect(str(path),timeout=5)
        os.chmod(path,0o600)
        self.db.row_factory=sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS queue(
          url TEXT PRIMARY KEY,depth INTEGER NOT NULL,status TEXT NOT NULL,parent TEXT,reason TEXT);
        CREATE TABLE IF NOT EXISTS docs(
          url TEXT PRIMARY KEY,title TEXT,text_sha TEXT,excerpt TEXT,source_mode TEXT,
          observed_utc TEXT,size_bytes INTEGER);
        CREATE TABLE IF NOT EXISTS candidates(
          id TEXT PRIMARY KEY,owner_scope TEXT NOT NULL,url TEXT NOT NULL REFERENCES docs(url),
          sha TEXT NOT NULL,summary TEXT NOT NULL,tags_json TEXT NOT NULL,
          namespace TEXT NOT NULL,status TEXT NOT NULL,confidence REAL NOT NULL,
          ttl_utc TEXT,created_utc TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS pheromone(
          candidate_id TEXT NOT NULL REFERENCES candidates(id),owner_scope TEXT NOT NULL,
          tag TEXT NOT NULL,namespace TEXT NOT NULL,strength REAL NOT NULL,
          status TEXT NOT NULL,evidence_sha TEXT NOT NULL,ttl_utc TEXT,
          PRIMARY KEY(candidate_id,tag));
        CREATE TABLE IF NOT EXISTS ledger(
          id TEXT PRIMARY KEY,model TEXT NOT NULL,estimate_usd TEXT NOT NULL,
          state TEXT NOT NULL,created_utc TEXT NOT NULL,response_sha TEXT);
        CREATE TABLE IF NOT EXISTS events(
          seq INTEGER PRIMARY KEY,time_utc TEXT NOT NULL,kind TEXT NOT NULL,
          body TEXT NOT NULL,prev_hash TEXT NOT NULL,hash TEXT NOT NULL UNIQUE);
        """)
        self.db.commit()
    def close(self):
        self.db.close()
    def get(self,key,default=None):
        row=self.db.execute("SELECT v FROM meta WHERE k=?",(key,)).fetchone()
        return json.loads(row[0]) if row else default
    def set(self,key,value):
        self.db.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                        (key,canonical(value)))
        self.db.commit()
    def event(self,kind,body):
        if not kind.isupper() or len(canonical(body))>2000:
            raise AdmissionError("unsafe event")
        last=self.db.execute("SELECT seq,hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        n=last["seq"]+1 if last else 1
        prev=last["hash"] if last else "0"*64
        now=stamp()
        entry={"seq":n,"time_utc":now,"kind":kind,"body":body,"prev_hash":prev}
        h=digest(entry)
        self.db.execute("INSERT INTO events VALUES(?,?,?,?,?,?)",
                        (n,now,kind,canonical(body),prev,h))
        self.db.commit()
        atomic_json(self.root/"head.json",{"schema":"nemotron48-head-v1","seq":n,"hash":h})
        return h
    def verify(self):
        head_file=self.root/"head.json"
        prev="0"*64
        n=0
        for row in self.db.execute("SELECT * FROM events ORDER BY seq"):
            n+=1
            obj={"seq":row["seq"],"time_utc":row["time_utc"],"kind":row["kind"],
                 "body":json.loads(row["body"]),"prev_hash":row["prev_hash"]}
            if row["seq"]!=n or row["prev_hash"]!=prev or digest(obj)!=row["hash"]:
                raise AdmissionError("invalid event chain; reject review")
            prev=row["hash"]
        if n==0 and head_file.exists():
            raise AdmissionError("truncated event chain")
        if n>0:
            if head_file.is_symlink() or not head_file.is_file():
                raise AdmissionError("missing head file")
            head=json.loads(head_file.read_text("utf-8"))
            if head.get("seq")!=n or head.get("hash")!=prev:
                raise AdmissionError("chain/head mismatch")
        return {"events":n,"head":prev,"integrity":"CONSISTENT_LOCAL_CHAIN_ONLY"}
    def enqueue(self,url,depth,parent=None):
        if self.count("queue")>=1200:
            return False
        cursor=self.db.execute("INSERT OR IGNORE INTO queue(url,depth,status,parent,reason) VALUES(?,?,?,?,?)",
                               (url,depth,"PENDING",parent,""))
        self.db.commit()
        return cursor.rowcount==1
    def next(self):
        return self.db.execute('SELECT url,depth FROM queue WHERE status="PENDING" ORDER BY depth,url LIMIT 1').fetchone()
    def mark(self,url,status,reason=""):
        if status not in {"IN_FLIGHT","OBSERVED","REJECTED","FAILED","FIXTURE_MISSING"}:
            raise AdmissionError("invalid queue state")
        self.db.execute("UPDATE queue SET status=?,reason=? WHERE url=?",
                        (status,str(reason)[:120],url))
        self.db.commit()
    def count(self,table):
        if table not in {"queue","docs","candidates","pheromone","ledger","events"}:
            raise AdmissionError("invalid table")
        return self.db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0]
    def bytes_seen(self):
        return self.db.execute("SELECT COALESCE(SUM(size_bytes),0) FROM docs").fetchone()[0]
    def initialize(self,*,owner,urls,hours=48,max_docs=200,max_bytes=8000000,max_depth=1):
        if self.get("mission") is not None:
            raise AdmissionError("sandbox already initialized")
        validate_owner(owner)
        if not 0<hours<=48 or not 1<=max_docs<=1000 or not 1000<=max_bytes<=30000000 or not 0<=max_depth<=2:
            raise AdmissionError("invalid mission quotas")
        meta={"schema":"nemotron48-mission-v1","owner_scope":owner,"seed_digest":digest(urls),
              "created_utc":stamp(),"hours":hours,"max_docs":max_docs,
              "max_total_bytes":max_bytes,"max_depth":max_depth,
              "status":"PLANNED","active_seconds":0.0,"last_session":None,
              "authority":"ADVISORY_ONLY","training":"NONE","knowledge_promotion":"DISABLED"}
        self.set("mission",meta)
        for url in urls:self.enqueue(url,0)
        self.event("MISSION_INITIALIZED",{"config_hash":digest(meta),"seeds":len(urls)})
        return meta
    def candidate(self,url,payload,mode,raw_size,*,summary=None,tags=None):
        if mode not in {"FIXTURE","LIVE_PUBLIC_DOC"} or raw_size>256000:
            raise AdmissionError("invalid document mode/size")
        already=self.db.execute("SELECT 1 FROM docs WHERE text_sha=?",(payload["sha256"],)).fetchone()
        self.db.execute("""INSERT OR REPLACE INTO docs
          (url,title,text_sha,excerpt,source_mode,observed_utc,size_bytes)
          VALUES(?,?,?,?,?,?,?)""",
          (url,payload["title"][:200],payload["sha256"],payload["text"][:8000],mode,stamp(),raw_size))
        candidate_id=None
        if not already:
            owner=self.get("mission")["owner_scope"]
            candidate_id=digest({"url":url,"owner":owner,"sha":payload["sha256"]})[:32]
            tags=sorted(set(tags if tags is not None else payload["tags"]))[:8]
            if any(not isinstance(x,str) or len(x)>40 or not x.isascii() or
                   not x.replace("-","").isalnum() for x in tags):
                raise AdmissionError("untrusted tag format")
            self.db.execute("""INSERT OR IGNORE INTO candidates
              (id,owner_scope,url,sha,summary,tags_json,namespace,status,confidence,ttl_utc,created_utc)
              VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
              (candidate_id,owner,url,payload["sha256"],(summary or payload["text"][:700])[:1200],
               canonical(tags),"web-design/experimental","UNVERIFIED_SHADOW",0.2,None,stamp()))
            for tag in tags:
                self.db.execute("""INSERT OR IGNORE INTO pheromone
                  (candidate_id,owner_scope,tag,namespace,strength,status,evidence_sha,ttl_utc)
                  VALUES(?,?,?,?,?,?,?,?)""",
                  (candidate_id,owner,tag,"web-design/experimental",0.2,"SHADOW",payload["sha256"],None))
        self.db.commit()
        return candidate_id
    def reserve(self,model,estimate:Decimal,*,cap:int,budget:Decimal):
        if estimate<=0 or not 1<=cap<=200 or not 0<budget<=Decimal("10"):
            raise AdmissionError("model reservation invalid")
        sums=[Decimal(x[0]) for x in self.db.execute("SELECT estimate_usd FROM ledger")]
        if len(sums)>=cap or sum(sums,Decimal(0))+estimate>budget:
            raise AdmissionError("money/call cap exceeded; no fallback")
        ident=uuid.uuid4().hex
        self.db.execute("INSERT INTO ledger VALUES(?,?,?,?,?,?)",
                        (ident,model,str(estimate),"RESERVED_UNCERTAIN",stamp(),None))
        self.db.commit()
        return ident
    def settle(self,ident,result):
        state="RESPONSE_VALIDATED" if result is not None else "UNKNOWN_BILLING_HELD"
        self.db.execute("UPDATE ledger SET state=?,response_sha=? WHERE id=?",
                        (state,digest(result) if result else None,ident))
        self.db.commit()
    def report(self):
        mission=self.get("mission")
        if mission is None:raise AdmissionError("mission not initialized")
        return {"mission":mission,
                "counts":{x:self.count(x) for x in
                  ("queue","docs","candidates","pheromone","ledger","events")},
                "queue_states":{x["status"]:x["n"] for x in
                  self.db.execute("SELECT status,COUNT(*) n FROM queue GROUP BY status")},
                "evidence":self.verify()}
    def export(self):
        self.verify()
        target=self.root/"knowledge_candidates_SHADOW.jsonl"
        if target.is_symlink():raise AdmissionError("export symlink forbidden")
        fd,tmp=tempfile.mkstemp(prefix=".export-",dir=str(self.root))
        try:
            os.fchmod(fd,0o600)
            with os.fdopen(fd,"w",encoding="utf-8") as file:
                for row in self.db.execute("SELECT * FROM candidates ORDER BY id"):
                    item=dict(row)
                    item["tags"]=json.loads(item.pop("tags_json"))
                    item["promotion_allowed"]=False
                    item["source_hash_is_truth_proof"]=False
                    file.write(canonical(item)+"\n")
                file.flush();os.fsync(file.fileno())
            os.replace(tmp,target)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        return target
