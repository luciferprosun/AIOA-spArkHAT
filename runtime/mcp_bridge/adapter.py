"""Adapters between the external Commander protocol and AIOA observations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping
import uuid

from .contracts import PROTOCOL_VERSION, RiskClass, TaskEnvelope, TaskResult
from .policy import expected_risk
from .read_ops import validate_read_payload


@dataclass(frozen=True)
class AIOAObservation:
    """A non-authoritative observation derived from a Commander result."""

    schema: str
    source: str
    authority: str
    can_authorize_effects: bool
    task_id: str
    state: str
    summary: str
    artifact_refs: tuple[str, ...]
    audit_refs: tuple[str, ...]
    changed_files: tuple[str, ...]
    metadata: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source": self.source,
            "authority": self.authority,
            "can_authorize_effects": self.can_authorize_effects,
            "task_id": self.task_id,
            "state": self.state,
            "summary": self.summary,
            "artifact_refs": list(self.artifact_refs),
            "audit_refs": list(self.audit_refs),
            "changed_files": list(self.changed_files),
            "metadata": dict(self.metadata),
        }


def build_task(
    operation: str,
    payload: dict[str, Any],
    *,
    target_project: str = "commander",
    task_id: str | None = None,
    idempotency_key: str | None = None,
    source: str = "chatgpt",
) -> TaskEnvelope:
    risk = expected_risk(operation)
    if risk is RiskClass.READ:
        validate_read_payload(operation, payload)
    if risk is None:
        # Unknown operations are still representable only at an explicitly
        # dangerous risk class so policy cannot accidentally treat them as READ.
        risk = RiskClass.OPEN_WORLD

    effective_task_id = task_id or f"task-{uuid.uuid4()}"
    effective_key = idempotency_key
    if effective_key is None:
        seed = f"{PROTOCOL_VERSION}:{effective_task_id}:{operation}".encode("utf-8")
        effective_key = hashlib.sha256(seed).hexdigest()

    return TaskEnvelope(
        task_id=effective_task_id,
        target_project=target_project,
        operation=operation,
        risk=risk,
        payload=payload,
        idempotency_key=effective_key,
        source=source,
    )


def admit_commander_result(result: TaskResult) -> AIOAObservation:
    """Convert a tool result to evidence-like data without granting authority."""

    return AIOAObservation(
        schema="aioa.mcp-observation.v1",
        source="mcp_commander",
        authority="ADVISORY_ONLY",
        can_authorize_effects=False,
        task_id=result.task_id,
        state=result.state.value,
        summary=result.summary,
        artifact_refs=result.artifact_ids,
        audit_refs=result.audit_refs,
        changed_files=result.changed_files,
        metadata=dict(result.metadata),
    )


class CoreMissionMCPAdapter:
    """MCP-facing typed port of one existing MissionService and Core store.

    Transport linkage is not authority. Only the separate native host can
    approve/run the exact pending operation. No server, signer or DB is added.
    """
    SCHEMA='aioa.core-mcp-link.v2'

    def __init__(self,missions,reader,*,project_root):
        from runtime.meta_hackathon.mission_service import MissionService
        from runtime.core_admission import Capability
        from .read_ops import bounded_public_license
        if type(missions) is not MissionService:raise ValueError('MCP_SAME_MISSION_REQUIRED')
        missions.core.require(reader,Capability.READ,scope=missions.scope)
        self.missions,self.reader,self.root=missions,reader,project_root
        self.source=tuple(missions.source_probe())
        self.license_sha256=bounded_public_license(project_root)['sha256']

    @staticmethod
    def _require(value,reason='MCP_CORE_DENIED'):
        if not value:raise ValueError(reason)

    def _check(self):
        from runtime.core_admission import Capability
        self.missions.core.require(self.reader,Capability.READ,scope=self.missions.scope)
        self._require(not self.missions._closed and tuple(self.missions.source_probe())==self.source,
                      'MCP_SOURCE_CHANGED')

    @staticmethod
    def _key(task_id):return 'mcp-core-'+hashlib.sha256(task_id.encode()).hexdigest()

    def _get(self,task_id):
        from runtime.core_admission import Capability
        from runtime.memory_patch.persistence.ports import RecordKind
        self._require(type(task_id) is str and 0<len(task_id)<=128)
        return self.missions._run(Capability.READ,lambda tx:tx.get(RecordKind.OPERATION,self._key(task_id)))

    def _save(self,data,row=None):
        from runtime.core_admission import Capability
        from runtime.memory_patch.persistence.ports import RecordKind,StoredRecord
        from runtime.memory_patch.persistence.idempotency import OperationBinding
        from runtime.memory_patch.audit import append_domain_event
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        def save(tx):
            current=tx.get(RecordKind.OPERATION,self._key(data['mcp_task_id']))
            self._require((row is None and current is None) or
                (row is not None and current is not None and current.revision==row.revision),'MCP_REPLAY')
            stored=StoredRecord(RecordKind.OPERATION,self._key(data['mcp_task_id']),self.missions.scope,
                row.revision+1 if row else 1,data)
            if row:tx.replace(stored,expected_revision=row.revision)
            else:tx.insert(stored)
            identity=canonical_sha256([stored.record_id,stored.revision])
            binding=OperationBinding.bind('mcp-change-'+identity,'MCP_CORE_LINK',{'record_digest':stored.payload_digest})
            append_domain_event(tx,binding,event_id='mcp-audit-'+identity,proof_id='mcp-outbox-'+identity,
                resource_id=stored.record_id,before=row.payload['state'] if row else None,after=data['state'],
                content_digest=stored.payload_digest,at=self.missions.ledger.clock())
        return self.missions._run(Capability.COMMIT,save)

    def submit(self,task,*,source_sha,capsule_digest,namespace='aioa',origin='OFFLINE_FIXTURE'):
        from datetime import datetime,timezone
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from .task_bus import encode_task,parse_task
        from .policy import evaluate_task,PolicyEffect
        from .read_ops import bounded_public_license
        self._check()
        self._require(type(task) is TaskEnvelope and namespace=='aioa' and origin=='OFFLINE_FIXTURE'
            and (source_sha,capsule_digest)==self.source,'MCP_SOURCE_NAMESPACE_ORIGIN_DENIED')
        task=parse_task(encode_task(task))  # existing strict schema/fingerprint parser
        self._require(task.target_project=='aioa' and task.source=='mcp_fixture','MCP_SOURCE_IDENTITY_DENIED')
        try:created=datetime.fromisoformat(task.created_at.replace('Z','+00:00'))
        except ValueError:raise ValueError('MCP_EXPIRY_DENIED') from None
        self._require(created.tzinfo is not None and -5<=(self.missions.ledger.clock()-created).total_seconds()<=120,
                      'MCP_EXPIRED')
        decision=evaluate_task(task)
        self._require(decision.effect is not PolicyEffect.DENY,'MCP_POLICY_DENIED')
        op,payload=task.operation,dict(task.payload)
        if op in ('fs.create_project','sandbox.request','recipe.request'):
            self._require(set(payload)=={'recipe_id','provider_id'} and payload['recipe_id']=='sensorbridge-v1'
                and payload['provider_id']=='meta_model_api','MCP_RECIPE_DENIED')
        elif op=='fs.read':self._require(payload['path']=='LICENSE','MCP_FILESYSTEM_SCOPE_DENIED')
        elif op in ('git.commit_preview','git.publish_propose'):
            self._require(set(payload)==({'source_task_id','kind'} if op=='git.publish_propose' else {'source_task_id'}))
            if op=='git.publish_propose':self._require(payload['kind'] in ('push','draft_pr'))
        elif op=='dependency.propose':self._require(set(payload)=={'plan'})
        else:self._require(op=='system.status' and payload=={},'MCP_UNBOUND_OPERATION')
        with self.missions._lock:
            self._require(self._get(task.task_id) is None,'MCP_REPLAY')
            data={'schema':self.SCHEMA,'state':'MCP_PENDING','mcp_task_id':task.task_id,
                'fingerprint':task.fingerprint,'source_sha':source_sha,'capsule_digest':capsule_digest,
                'decision':decision.effect.value,'mission_id':None,'read':None,'proposal':None,
                'authority':'NONE','can_authorize_effects':False,'automatic_retry':False}
            self._save(data)
            request_id=canonical_sha256([task.task_id,task.idempotency_key,task.fingerprint])[:32]
            if op=='fs.read':
                observed=bounded_public_license(self.root,maximum=payload.get('bytes',8192))
                self._require(observed['sha256']==self.license_sha256,'MCP_FILE_CHANGED')
                if 'lines' in payload:observed['text']=''.join(observed['text'].splitlines(keepends=True)[:payload['lines']])
                data['read']=observed
            elif op=='system.status':data['read']={'core':'BOUND_OFFLINE_FIXTURE','live_verified':False,
                'agent_tools_bound':hasattr(self.missions,'agent_route'),'source_sha':source_sha}
            elif op=='git.commit_preview':
                result=self.missions.propose_git(payload['source_task_id'],request_id,self.reader,device_id='mcp-fixture')
                data['mission_id']=result['task_id']
            elif op=='git.publish_propose':
                result=self.missions.agent_view(payload['source_task_id'],self.reader)
                self._require(result['state']=='AGENT_COMPLETED' and result['receipt'].get('git') is not None,
                    'MCP_VERIFIED_GIT_SOURCE_REQUIRED')
                data['proposal']={'operation':payload['kind'],'git':result['git'],'effect_enabled':False,
                    'status':'NEEDS_HOST_APPROVAL','source_receipt_sha256':canonical_sha256(result['receipt'])}
            elif op=='dependency.propose':
                result=self.missions.propose_install(payload['plan'],request_id,self.reader,device_id='mcp-fixture')
                data['mission_id']=result['task_id']
            else:
                result=self.missions.propose_agent({'schema':'aioa.agent-proposal.v2',**payload,
                    'request_id':request_id},self.reader,device_id='mcp-fixture')
                data['mission_id']=result['task_id']
            self._check()
            row=self._get(task.task_id);data['state']='MCP_LINKED'
            self._save(data,row)
            return self.result(task.task_id)

    def result(self,task_id):
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        import json
        self._check();row=self._get(task_id)
        self._require(row is not None and row.payload.get('schema')==self.SCHEMA,'MCP_NOT_FOUND')
        data=json.loads(canonical_json_bytes(row.payload))
        data['mission']=None if data['mission_id'] is None else self.missions.agent_view(data['mission_id'],self.reader)
        if data['state']=='MCP_PENDING':data.update(state='UNKNOWN',readback_required=True)
        return data
