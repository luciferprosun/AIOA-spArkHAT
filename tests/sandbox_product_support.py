"""Trusted offline native Core fixture for explicit kernel acceptance only."""
from dataclasses import replace
import test_core_tool_composition as base
from test_dual_governor import MODEL
from lab.archaioa.faults import FaultKind,FaultTrace,classify_fault
from lab.archaioa.taint import DependencyGraph,DependencyNode,NodeKind
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.tools import CoreToolRoute
from runtime.mission.sandbox_linux import prepare_linux_sandbox,LinuxSandboxBroker
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.governor import ReservationRequest
from runtime.providers.nvidia import ProviderRequest,ProviderResponse
from runtime.mission.job_contracts import JobEnvelope

def core_case(config,identity,*,project_plan=None):
    fixture=base.CoreToolCompositionTests('test_real_synthetic_attempt_opens_required_g2_and_holds_exposure')
    fixture.setUp();fx=fixture.fx;broker=LinuxSandboxBroker(config)
    if project_plan is not None:
        from runtime.mission.project_recipe import PythonProjectPlan
        from runtime.mission.tasklist_recipe import TaskListPlan
        assert type(project_plan) in (PythonProjectPlan, TaskListPlan)
        fixture.current=replace(fixture.current,fingerprint=project_plan.target_fingerprint,
            revision='project-r'+str(project_plan.expected_revision))
    route=CoreToolRoute(fx.journal,fixture.liability,workspace='workspace-1',policy_revision=2,
        variant='sandbox',sandbox_registry=config.registry,probe=lambda:fixture.current,
        executor=broker,target_guard=lambda:fixture.lifecycle,verifier=broker.verify,clock=lambda:fixture.now)
    operation=route.operation({'action':'run_recipe','recipe_id':identity,'task_id':'product-task','step_id':'effect'},fixture.current)
    trace=FaultTrace(FaultKind.LOST_ACK,'product-task','product-request','sha256:'+canonical_sha256(operation))
    graph=DependencyGraph('product-task',(DependencyNode('effect',NodeKind.OPERATION,
        liability_ids=(classify_fault(trace).liability_id,)),DependencyNode('completion',NodeKind.COMPLETION_CANDIDATE,('effect',))))
    binding=TaskCompletionBinding.for_graph(fx.ledger.scope,graph,'completion')
    fixture.liability.initialize(fx.p(),graph)
    request=ProviderRequest('product-advisory','product-trace','nebius',MODEL,'offline fixture','budget',128,20)
    envelope=JobEnvelope.from_request(fx.ledger.scope,graph.task_id,request,deadline_at=160,money_nano=1,risk_units=0)
    fx.gov.submit_job(fx.p(Capability.MANAGE),envelope,completion=binding)
    claim=fx.gov.claim_job(fx.p(),graph.task_id,'fixture-worker',1,lease_seconds=30);fx.gov.begin_job(fx.p(),claim)
    grant=replace(fixture.grant,session_id='product-session',policy_revision=2,
        capabilities=('PROJECT_WRITE','SANDBOX_EXEC'),completion_digest=binding.digest)
    route.create_session(fx.p(Capability.OWNER_APPROVAL),grant)
    warrant=route.authorize(fx.p(),grant.session_id,operation,binding,graph,trace,
        nonce='product-nonce',model_id=MODEL,money_nano=40,risk_units=5)
    reservation=ReservationRequest(warrant.money_reservation_id,graph.task_id,'sandbox-exec',MODEL,canonical_sha256(operation),40,5)
    arguments=dict(session_id=grant.session_id,warrant=warrant,operation=operation,reservation=reservation,completion=binding)
    fixture.product_claim=claim;fixture.product_request=request;fixture.product_binding=binding
    return fixture,route,warrant,arguments
