"""Metadata minimization over real Core-admitted native retrieval lanes."""
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

from runtime.core_admission import AdmissionError, Capability, OwnerScope
from runtime.evidence_admission import EvidenceAdmissionError
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.errors import ErrorCode, KernelContractError, MemoryPatchError
from runtime.memory_patch.retrieval.contracts import FrozenEvidenceBundle, HybridRetrievalRequest
from test_memory_patch_persistence_ports import NOW
from test_memory_patch_retrieval import RetrievalFixture


DENIAL = (AdmissionError, EvidenceAdmissionError, MemoryPatchError, KernelContractError)


class CapsuleClosedContractTests(unittest.TestCase):
    def make(self, **changes):
        from runtime.memory_patch.retrieval.capsule import ContextCapsule
        fields = dict(request_hash='0'*64, bundle_hash='1'*64, scope_ref='2'*64,
                      hat_ref='3'*64, byte_budget=65536, context_refs=({
                          'lane': 'CANONICAL_EVIDENCE', 'binding_ref': '4'*64,
                          'reference_ref': '5'*64, 'source_binding_ref': '6'*64,
                          'canonical_evidence': True},))
        fields.update(changes)
        return ContextCapsule(**fields)

    def rehash(self, cap):
        object.__setattr__(cap, 'capsule_hash', canonical_sha256(cap, exclude_fields=('capsule_hash',)))

    def test_direct_construction_cannot_export_raw_commands_or_approval_material(self):
        with self.assertRaises(DENIAL):
            self.make(context_refs=({'command': 'RAW_COMMAND_SENTINEL',
                                     'approval_token': '<example-only>'},)).as_dict()

    def test_reference_schema_rejects_extra_payload_fields(self):
        ref = dict(self.make().context_refs[0]); ref['reasoning_content'] = 'RAW_REASONING_SENTINEL'
        with self.assertRaises(DENIAL):
            self.make(context_refs=(ref,))

    def test_all_top_level_binding_values_must_be_exact_digests(self):
        for field in ('request_hash', 'bundle_hash', 'scope_ref', 'hat_ref'):
            with self.assertRaises(DENIAL):
                self.make(**{field: 'RAW_CONTEXT_SENTINEL'})

    def test_reference_binding_values_must_be_exact_digests(self):
        for field in ('binding_ref', 'reference_ref', 'source_binding_ref'):
            ref = dict(self.make().context_refs[0]); ref[field] = 'RAW_CONTEXT_SENTINEL'
            with self.assertRaises(DENIAL):
                self.make(context_refs=(ref,))

    def test_unknown_lane_is_rejected(self):
        ref = dict(self.make().context_refs[0]); ref['lane'] = 'EFFECT_AUTHORITY'
        with self.assertRaises(DENIAL):
            self.make(context_refs=(ref,))

    def test_owner_reference_cannot_be_promoted_to_canonical_evidence(self):
        ref = dict(self.make().context_refs[0]); ref['lane'] = 'OWNER_CONTEXT'
        with self.assertRaises(DENIAL):
            self.make(context_refs=(ref,))

    def test_budget_is_a_bounded_integer_not_a_boolean(self):
        for budget in (True, 0, 262145, 65536.0):
            with self.assertRaises(DENIAL):
                self.make(byte_budget=budget)

    def test_duplicate_references_are_rejected(self):
        ref = dict(self.make().context_refs[0])
        with self.assertRaises(DENIAL):
            self.make(context_refs=(ref, ref))

    def test_reference_collection_is_bounded(self):
        refs = tuple(dict(self.make().context_refs[0], binding_ref=f'{number:064x}',
                          reference_ref=f'{number+100:064x}') for number in range(41))
        with self.assertRaises(DENIAL):
            self.make(context_refs=refs)

    def test_rehashed_authority_purpose_or_schema_cannot_be_exported(self):
        for field, changed in (('authority', 'APPROVED'), ('purpose', 'EXECUTION'),
                               ('schema', 'future-schema')):
            cap = self.make(); object.__setattr__(cap, field, changed); self.rehash(cap)
            with self.assertRaises(DENIAL):
                cap.as_dict()

    def test_export_rechecks_complete_byte_budget_after_rehash(self):
        cap = self.make(); object.__setattr__(cap, 'byte_budget', 256); self.rehash(cap)
        with self.assertRaises(DENIAL):
            cap.as_dict()

    def test_export_rechecks_closed_reference_schema_after_rehash(self):
        from runtime.memory_patch.contracts.serialization import freeze_json
        cap = self.make(); ref = dict(cap.context_refs[0]); ref['command'] = 'RAW_COMMAND_SENTINEL'
        object.__setattr__(cap, 'context_refs', freeze_json((ref,))); self.rehash(cap)
        with self.assertRaises(DENIAL):
            cap.as_dict()

    def test_export_rechecks_binding_digest_after_rehash(self):
        cap = self.make(); object.__setattr__(cap, 'hat_ref', 'RAW_CONTEXT_SENTINEL'); self.rehash(cap)
        with self.assertRaises(DENIAL):
            cap.as_dict()


class ContextCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.fx = RetrievalFixture()
        self.a = self.fx.candidate(source_id='source-a')
        self.b = self.fx.candidate(source_id='source-b', content='A second reviewed rule applies.')
        self.fx.sources.values = (self.fx.ranked_input(self.a), self.fx.ranked_input(self.b, rank=2))
        self.lanes = self.fx.service.retrieve(self.fx.reader, self.fx.request)

    def capsule(self, *, request=None, lanes=None, selected_refs=None, principal=None):
        method = getattr(self.fx.service, 'context_capsule', None)
        self.assertTrue(callable(method), 'Missing native bounded context capsule projection')
        return method(principal or self.fx.reader, request or self.fx.request,
                      lanes or self.lanes, selected_refs=selected_refs)

    def test_binds_native_hashes_scope_and_has_no_raw_context_or_authority(self):
        cap = self.capsule()
        value = cap.as_dict()
        self.assertEqual(self.fx.request.request_hash, value['request_hash'])
        self.assertEqual(self.lanes.canonical_evidence.bundle_hash, value['bundle_hash'])
        self.assertEqual(canonical_sha256(self.fx.reader.scope), value['scope_ref'])
        self.assertEqual(canonical_sha256('test-hat'), value['hat_ref'])
        self.assertEqual('NONE', value['authority'])
        self.assertEqual('ADVISORY_CONTEXT_ONLY', value['purpose'])
        self.assertEqual(2, len(value['context_refs']))
        raw = canonical_json_bytes(cap).decode()
        for excluded in [self.a.content, self.fx.reader.scope.owner_id, 'approval_token',
                         'effect_warrant', 'private_key', 'reasoning_content', 'command']:
            self.assertNotIn(excluded, raw)

    def test_explicit_least_context_selection_does_not_export_other_admitted_items(self):
        item = self.lanes.temporal.applicable_items[0]
        cap = self.capsule(selected_refs=(('CANONICAL_EVIDENCE', item.item_hash),))
        self.assertEqual(1, len(cap.context_refs))
        self.assertEqual(item.item_hash, cap.context_refs[0]['binding_ref'])
        self.assertEqual(self.lanes.canonical_evidence.bundle_hash, cap.bundle_hash)

    def test_selection_order_does_not_change_digest(self):
        refs = tuple(('CANONICAL_EVIDENCE', x.item_hash) for x in self.lanes.temporal.applicable_items)
        self.assertEqual(self.capsule(selected_refs=refs), self.capsule(selected_refs=tuple(reversed(refs))))

    def test_capsule_is_immutable_and_export_cannot_modify_it(self):
        cap = self.capsule()
        raw = canonical_json_bytes(cap)
        with self.assertRaises(FrozenInstanceError):
            cap.bundle_hash = '0'*64
        with self.assertRaises(TypeError):
            cap.context_refs[0]['lane'] = 'OWNER_CONTEXT'
        exported = cap.as_dict(); exported['context_refs'].clear()
        self.assertEqual(raw, canonical_json_bytes(cap))

    def test_hard_budget_overflow_fails_closed_even_for_empty_selection(self):
        request = replace(self.fx.request, context_budget_bytes=256)
        self.fx.request = request
        self.fx.sources.values = (self.fx.ranked_input(self.a), self.fx.ranked_input(self.b, rank=2))
        lanes = self.fx.service.retrieve(self.fx.reader, request)
        with self.assertRaises(MemoryPatchError) as caught:
            self.capsule(request=request, lanes=lanes, selected_refs=())
        self.assertIs(caught.exception.code, ErrorCode.QUOTA_EXCEEDED)

    def test_changed_request_cannot_reuse_original_bundle(self):
        with self.assertRaises(DENIAL):
            self.capsule(request=replace(self.fx.request, query='changed request'))

    def test_tampered_cached_request_hash_is_denied(self):
        object.__setattr__(self.fx.request, 'query', 'changed without updating request hash')
        with self.assertRaises(DENIAL):
            self.capsule()

    def test_tampered_cached_bundle_is_denied(self):
        object.__setattr__(self.lanes.canonical_evidence, 'items', ())
        with self.assertRaises(DENIAL):
            self.capsule()

    def test_rehashed_foreign_request_bundle_is_denied(self):
        bundle = replace(self.lanes.canonical_evidence, request_hash='0'*64)
        with self.assertRaises(DENIAL):
            self.capsule(lanes=replace(self.lanes, canonical_evidence=bundle))

    def rebound(self, request, *, items=None):
        from runtime.memory_patch.retrieval.temporal import TemporalQueryMode, resolve_temporal
        old = self.lanes.canonical_evidence
        selected = old.items if items is None else items
        bindings = tuple((item.item_hash, dict(old.core_evidence_bindings)[original.item_hash])
                         for item, original in zip(selected, old.items))
        bundle = replace(old, request_hash=request.request_hash, items=selected,
                         core_evidence_bindings=bindings)
        temporal = resolve_temporal(bundle, mode=TemporalQueryMode.CURRENT,
                                    trusted_now=self.lanes.temporal.as_of, freshness=self.fx.service.freshness)
        return replace(self.lanes, canonical_evidence=bundle, temporal=temporal)

    def test_rehashed_outer_bundle_cannot_relabel_native_request_lineage(self):
        changed = replace(self.fx.request, query='Different request with old native contributions')
        rebound = self.rebound(changed)
        self.assertNotEqual(changed.request_hash, rebound.canonical_evidence.items[0].contributions[0].upstream_request_hash)
        with self.assertRaises(DENIAL):
            self.capsule(request=changed, lanes=rebound)

    def test_rehashed_invalid_native_request_bounds_are_denied_even_without_items(self):
        request = self.fx.request
        object.__setattr__(request, 'limit', 41)
        object.__setattr__(request, 'request_hash', canonical_sha256(request, exclude_fields=('request_hash',)))
        with self.assertRaises(DENIAL):
            self.capsule(request=request, lanes=self.rebound(request, items=()))

    def test_rehashed_native_request_derived_identity_is_denied_even_without_items(self):
        request = self.fx.request
        object.__setattr__(request, 'embedding_model_digest', '0'*64)
        object.__setattr__(request, 'request_hash', canonical_sha256(request, exclude_fields=('request_hash',)))
        with self.assertRaises(DENIAL):
            self.capsule(request=request, lanes=self.rebound(request, items=()))

    def test_rehashed_outer_item_cannot_hide_invalid_nested_contribution_hash(self):
        item = self.lanes.canonical_evidence.items[0]
        object.__setattr__(item.contributions[0], 'upstream_result_hash', 'f'*64)
        object.__setattr__(item, 'item_hash', canonical_sha256(item, exclude_fields=('item_hash',)))
        old = self.lanes.canonical_evidence
        bindings = ((item.item_hash, old.core_evidence_bindings[0][1]), *old.core_evidence_bindings[1:])
        bundle = replace(old, core_evidence_bindings=bindings)
        from runtime.memory_patch.retrieval.temporal import TemporalQueryMode, resolve_temporal
        temporal = resolve_temporal(bundle, mode=TemporalQueryMode.CURRENT,
                                    trusted_now=self.lanes.temporal.as_of, freshness=self.fx.service.freshness)
        with self.assertRaises(DENIAL):
            self.capsule(lanes=replace(self.lanes, canonical_evidence=bundle, temporal=temporal))

    def test_cross_owner_cannot_project_the_bundle(self):
        from test_memory_patch_persistence_ports import make_admission
        other = make_admission(tenant='foreign-tenant', owner='foreign-owner')
        with self.assertRaises(DENIAL):
            self.capsule(principal=other.local_operator(Capability.READ))

    def test_hat_mismatch_is_denied(self):
        bundle = self.lanes.canonical_evidence
        object.__setattr__(bundle, 'hat_scope_id', 'foreign-hat')
        object.__setattr__(bundle, 'bundle_hash', canonical_sha256(bundle, exclude_fields=('bundle_hash',)))
        with self.assertRaises(DENIAL):
            self.capsule()

    def test_wrong_capability_cannot_project(self):
        with self.assertRaises(DENIAL):
            self.capsule(principal=self.fx.core.local_operator(Capability.COMMIT))

    def test_rehashed_invalid_source_registry_binding_is_denied(self):
        old = self.lanes.canonical_evidence
        item = replace(old.items[0], registry_digest='0'*64)
        bundle = replace(old, items=(item,*old.items[1:]),
                         core_evidence_bindings=((item.item_hash,dict(old.core_evidence_bindings)[old.items[0].item_hash]),
                                                 *old.core_evidence_bindings[1:]))
        with self.assertRaises(DENIAL):
            self.capsule(lanes=replace(self.lanes, canonical_evidence=bundle))

    def test_withdrawn_source_fails_current_admission(self):
        record = self.fx.catalog.records[self.a.core_evidence_id]
        self.fx.catalog.records[record.evidence_id] = replace(record, withdrawn=True)
        with self.assertRaises(DENIAL):
            self.capsule()

    def test_stale_bundle_is_denied_at_projection(self):
        self.fx.service.clock = lambda: NOW+timedelta(days=2)
        with self.assertRaises(DENIAL):
            self.capsule()

    def test_tampered_temporal_selection_is_denied(self):
        state = self.lanes.temporal.states[0]
        temporal = replace(self.lanes.temporal, states=(replace(state, integrity_valid=False),*self.lanes.temporal.states[1:]))
        with self.assertRaises(DENIAL):
            self.capsule(lanes=replace(self.lanes, temporal=temporal))

    def test_reference_outside_admitted_lanes_is_denied(self):
        with self.assertRaises(DENIAL):
            self.capsule(selected_refs=(('CANONICAL_EVIDENCE','0'*64),))

    def test_duplicate_reference_is_denied(self):
        ref = ('CANONICAL_EVIDENCE',self.lanes.temporal.applicable_items[0].item_hash)
        with self.assertRaises(DENIAL):
            self.capsule(selected_refs=(ref,ref))

    def test_new_available_source_does_not_expand_admitted_capsule(self):
        first = self.capsule()
        added = self.fx.candidate(source_id='source-new',content='Unselected new context.')
        self.fx.sources.values += (self.fx.ranked_input(added,rank=3),)
        self.assertEqual(first,self.capsule())


class NativePersonalCapsuleTests(unittest.TestCase):
    def setUp(self):
        from nv03_support import MemoryFixture
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'memory'
        self.fx = MemoryFixture(self.root); self.addCleanup(self.fx.close)
        self.patch = self.fx.activate(text={'language':'pl'},content_kind='PREFERENCE')
        self.reader = self.fx.core.local_operator(Capability.READ)
        self.service = self.fx.runtime._lite_memory.service.retrieval
        self.request = HybridRetrievalRequest.admitted(self.fx.core,self.reader,hat_id=self.fx.hat_id,query='reviewed policy')
        self.lanes = self.service.retrieve(self.reader,self.request)

    def capsule(self):
        method=getattr(self.service,'context_capsule',None)
        self.assertTrue(callable(method),'Missing native bounded context capsule projection')
        return method(self.reader,self.request,self.lanes)

    def test_personal_context_stays_owner_scoped_and_not_canonical(self):
        before=(self.root/'memory.json').read_bytes()
        cap=self.capsule()
        owners=[r for r in cap.context_refs if r['lane']=='OWNER_CONTEXT']
        self.assertEqual(1,len(owners))
        self.assertIs(owners[0]['canonical_evidence'],False)
        self.assertEqual(before,(self.root/'memory.json').read_bytes())
        self.assertNotIn('language',json.dumps(cap.as_dict()))
        self.assertNotIn(self.patch,json.dumps(cap.as_dict()))

    def test_tampered_personal_body_cannot_reuse_owner_record(self):
        personal=replace(self.lanes.personal_context[0],content='Changed after admission')
        self.lanes=replace(self.lanes,personal_context=(personal,))
        with self.assertRaises(DENIAL):
            self.capsule()

    def test_revoked_personal_context_is_denied(self):
        self.fx.op('revoke',patch_id=self.patch,expected_revision=self.fx.raw_patch(self.patch).revision,
                   operation_key='capsule-revoke')
        with self.assertRaises(DENIAL):
            self.capsule()

    def test_same_admitted_inputs_survive_native_restart_with_identical_digest(self):
        from nv03_support import MemoryFixture
        first=self.capsule()
        self.fx.close()
        restarted=MemoryFixture(self.root)
        try:
            reader=restarted.core.local_operator(Capability.READ)
            second=restarted.runtime._lite_memory.service.retrieval.context_capsule(reader,self.request,self.lanes)
            self.assertEqual(first,second)
        finally:
            restarted.close()
