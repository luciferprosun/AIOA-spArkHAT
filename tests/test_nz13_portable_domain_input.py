"""Closed physical-input facts; never a Core approval or physical execution test."""
import copy
import importlib
import importlib.util
import unittest
from datetime import UTC, datetime, timedelta

from nonzero_cloudops.adapters import portable
from nonzero_cloudops.investigation import QueryResource
from nonzero_cloudops.models import (
    BudgetCounters,
    LocalApprovalRequestRecord,
    ProposalState,
    RemediationOperation,
    RemediationProposal,
    ResourceQuery,
    Run,
    generate_proposal_id,
    generate_run_id,
    generate_trace_id,
)
from nonzero_cloudops.models.public_enums import AuthorityGate

from runtime.memory_patch.contracts.serialization import canonical_json_bytes


class PortableDomainInputTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mission.portable_target'),
                             'CLOSED_PORTABLE_DOMAIN_INPUT_NOT_IMPLEMENTED')
        self.api = importlib.import_module('runtime.mission.portable_target').PortableDomainInput
        self.now = datetime(2026, 11, 9, tzinfo=UTC)
        self.resources = tuple(portable.default_mock_resources())
        resource = next(item for item in self.resources
                        if isinstance(item, portable.ElasticIpResource) and item.association_id is None)
        self.run = Run.new(run_id=generate_run_id(), trace_id=generate_trace_id(),
                           correlation_id=generate_run_id(), idempotency_key='owned-fixture-input-once',
                           created_at=self.now, budget=BudgetCounters(max_turns=1, max_tokens=1))
        class ReadOnlyFacts:
            adapter_name = 'private-owned-fixture'

            def get_resource(inner, query):
                return resource

        self.evidence = QueryResource(ReadOnlyFacts()).execute(
            ResourceQuery(resource_type=resource.resource_type, resource_id=resource.resource_id,
                          region=resource.region), run=self.run, observed_at=self.now).value
        self.proposal = RemediationProposal.create(
            proposal_id=generate_proposal_id(), evidence=self.evidence,
            operation_type=RemediationOperation.RELEASE_ELASTIC_IP,
            normalized_parameters={'allocation_id': resource.resource_id},
            authority_class=AuthorityGate.PLAN_AND_CONFIRM,
            risk_summary='One owned local fixture address', created_at=self.now,
            expires_at=self.now + timedelta(minutes=2),
        ).model_copy(update={'status': ProposalState.AWAITING_APPROVAL})
        self.request = LocalApprovalRequestRecord.create(
            request_id=generate_proposal_id(), proposal=self.proposal, actor_session_id='a' * 64,
            decision_nonce_hash='b' * 64, requested_at=self.now,
            expires_at=self.now + timedelta(minutes=1))
        values = {(item.resource_type, item.resource_id, item.region): item for item in self.resources}
        self.payload = {
            'schema': 'aioa.portable-domain-input.v1',
            'proposal': self.proposal.model_dump(mode='json'),
            'evidence': self.evidence.model_dump(mode='json'),
            'request': self.request.model_dump(mode='json'),
            'inventory': portable.PortableStateStore._payload(values, {}),
        }

    def parse(self, value=None):
        return self.api(canonical_json_bytes(self.payload if value is None else value))

    def refused(self, value, reason):
        with self.assertRaisesRegex(ValueError, '^' + reason + '$'):
            self.parse(value)

    def test_valid_exact_pack_is_facts_only_and_has_complete_storage_root(self):
        pack = self.parse()
        expected = portable.PortableInventoryObservation(
            portable._canonical_inventory_bytes(self.payload['inventory']), (1,) * 8)
        self.assertEqual(expected.state_root, pack.state_root)
        self.assertEqual(expected.resources_root, pack.resources_root)
        self.assertEqual(expected.receipts_root, pack.receipts_root)
        self.assertEqual('NONE', pack.authority)
        self.assertEqual(self.payload, pack.to_dict())

    def test_nested_values_are_captured_and_each_read_is_independent(self):
        pack = self.parse()
        self.payload['proposal']['normalized_parameters']['allocation_id'] = 'changed'
        output = pack.to_dict()
        output['inventory']['resources'].clear()
        self.assertNotEqual(self.payload, pack.to_dict())
        self.assertEqual(len(self.resources), len(pack.to_dict()['inventory']['resources']))
        with self.assertRaises(AttributeError):
            pack.canonical_input = b'changed'

    def test_unknown_top_level_or_authority_fields_are_not_ignored(self):
        for field, value in [('approved', True), ('executor', 'local'), ('path', '/tmp/elsewhere')]:
            with self.subTest(field=field):
                self.refused({**self.payload, field: value}, 'PORTABLE_INPUT_SHAPE')

    def test_noncanonical_or_duplicate_json_members_are_refused(self):
        raw = canonical_json_bytes(self.payload)
        for value in [raw + b' ', b'{"schema":"wrong",' + raw[1:]]:
            with self.subTest(value_length=len(value)), self.assertRaisesRegex(
                    ValueError, '^PORTABLE_INPUT_CANONICAL$'):
                self.api(value)

    def test_unknown_version_is_refused(self):
        self.refused({**self.payload, 'schema': 'aioa.portable-domain-input.v2'}, 'PORTABLE_INPUT_SHAPE')

    def test_forged_proposal_hash_is_revalidated_from_json(self):
        value = copy.deepcopy(self.payload)
        value['proposal']['proposal_hash'] = '0' * 64
        self.refused(value, 'PORTABLE_INPUT_DOMAIN')

    def test_forged_evidence_hash_is_revalidated_from_json(self):
        value = copy.deepcopy(self.payload)
        value['evidence']['evidence_hash'] = '0' * 64
        self.refused(value, 'PORTABLE_INPUT_DOMAIN')

    def test_coherent_request_for_another_run_cannot_change_only_one_join(self):
        value = copy.deepcopy(self.payload)
        value['request']['run_id'] = str(generate_proposal_id())
        # A coherent request still has to match the exact proposal and evidence.
        request = self.request.model_copy(update={'run_id': value['request']['run_id']})
        from nonzero_cloudops.models.contracts import _canonical_digest
        value['request']['request_hash'] = _canonical_digest(request.binding_payload())
        self.refused(value, 'PORTABLE_INPUT_REQUEST_BINDING')

    def test_pending_proposal_is_required(self):
        value = copy.deepcopy(self.payload)
        value['proposal']['status'] = ProposalState.PROPOSED.value
        self.refused(value, 'PORTABLE_INPUT_OPERATION_DENIED')

    def test_other_operations_and_implicit_parameters_cannot_enter_release_profile(self):
        value = copy.deepcopy(self.payload)
        value['proposal']['normalized_parameters']['extra'] = True
        from nonzero_cloudops.models.contracts import _canonical_digest
        proposal = self.proposal.model_copy(update={
            'normalized_parameters': value['proposal']['normalized_parameters']})
        value['proposal']['proposal_hash'] = _canonical_digest(proposal.action_payload())
        self.refused(value, 'PORTABLE_INPUT_OPERATION_DENIED')

    def test_evidence_must_match_the_existing_complete_resource(self):
        value = copy.deepcopy(self.payload)
        target = next(item for item in value['inventory']['resources']
                      if item['resource_id'] == self.proposal.target_resource_id)
        target['tags']['fixture'] = 'drift'
        self.refused(value, 'PORTABLE_INPUT_TARGET_DRIFT')

    def test_absent_target_is_not_a_no_effect_or_success_certificate(self):
        value = copy.deepcopy(self.payload)
        value['inventory']['resources'] = [item for item in value['inventory']['resources']
            if item['resource_id'] != self.proposal.target_resource_id]
        self.refused(value, 'PORTABLE_INPUT_TARGET_DRIFT')

    def test_duplicate_resource_identity_is_refused_before_any_authority(self):
        value = copy.deepcopy(self.payload)
        value['inventory']['resources'].append(copy.deepcopy(value['inventory']['resources'][0]))
        self.refused(value, 'PORTABLE_INPUT_INVENTORY')

    def test_inventory_unknown_fields_and_boolean_version_are_refused(self):
        for fields in [{'extra': 1}, {'format_version': True}]:
            value = copy.deepcopy(self.payload)
            value['inventory'].update(fields)
            with self.subTest(fields=fields):
                self.refused(value, 'PORTABLE_INPUT_INVENTORY')

    def test_coercible_or_missing_inventory_fields_are_not_silently_normalized(self):
        value = copy.deepcopy(self.payload)
        value['inventory']['resources'][0].pop('tags')
        self.refused(value, 'PORTABLE_INPUT_INVENTORY')

    def test_complete_other_resource_and_all_receipts_are_committed(self):
        first = self.parse()
        value = copy.deepcopy(self.payload)
        other = next(item for item in value['inventory']['resources']
                     if item['resource_id'] != self.proposal.target_resource_id)
        other['tags']['fixture'] = 'different-owned-resource'
        second = self.parse(value)
        self.assertNotEqual(first.state_root, second.state_root)
        self.assertNotEqual(first.resources_root, second.resources_root)
        self.assertEqual(first.receipts_root, second.receipts_root)

    def test_request_time_and_lifetime_must_fit_the_exact_proposal(self):
        from nonzero_cloudops.models.contracts import _canonical_digest
        value = copy.deepcopy(self.payload)
        request = self.request.model_copy(update={'requested_at': self.now - timedelta(seconds=1)})
        request = request.model_copy(update={'request_hash': _canonical_digest(request.binding_payload())})
        value['request'] = request.model_dump(mode='json')
        self.refused(value, 'PORTABLE_INPUT_REQUEST_BINDING')

    def test_raw_input_type_size_and_invalid_json_are_fail_closed(self):
        for raw in [bytearray(b'{}'), '{}', b'{', b'x' * 49153, b'[]']:
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(ValueError):
                self.api(raw)


    def historical_receipt(self, *, current=False):
        from nonzero_cloudops.models import LocalExecutionReceipt
        from nonzero_cloudops.models.digest import compute_evidence_digest
        run_id = self.proposal.run_id if current else generate_run_id()
        values = {
            'run_id': run_id, 'proposal_id': self.proposal.proposal_id,
            'proposal_hash': self.proposal.proposal_hash, 'evidence_hash': self.evidence.evidence_hash,
            'decision_hash': 'c' * 64, 'intent_hash': 'd' * 64,
            'idempotency_key': f'local-exec:{run_id}:{self.proposal.proposal_hash}',
            'operation_type': self.proposal.operation_type,
            'target_resource_type': self.proposal.target_resource_type,
            'target_resource_id': self.proposal.target_resource_id,
            'before_resource': self.evidence.resource, 'after_resource': None,
            'executed_at': self.now - timedelta(seconds=10),
        }
        provisional = LocalExecutionReceipt.model_construct(**values, receipt_hash='0' * 64)
        return LocalExecutionReceipt(**values,
            receipt_hash=compute_evidence_digest(provisional.receipt_payload()))

    def test_domain_numeric_coercion_does_not_change_the_exact_approved_bytes(self):
        value = copy.deepcopy(self.payload)
        value['proposal']['version'] = '1'
        self.refused(value, 'PORTABLE_INPUT_DOMAIN_CANONICAL')

    def test_domain_defaults_cannot_fill_missing_approved_content(self):
        value = copy.deepcopy(self.payload)
        value['proposal'].pop('authorizes_execution')
        self.refused(value, 'PORTABLE_INPUT_DOMAIN_CANONICAL')

    def test_request_cannot_outlive_proposal_and_returns_constant_denial(self):
        from nonzero_cloudops.models.contracts import _canonical_digest
        request = self.request.model_copy(update={'expires_at': self.proposal.expires_at + timedelta(seconds=1)})
        request = request.model_copy(update={'request_hash': _canonical_digest(request.binding_payload())})
        value = copy.deepcopy(self.payload)
        value['request'] = request.model_dump(mode='json')
        self.refused(value, 'PORTABLE_INPUT_REQUEST_BINDING')

    def test_current_run_receipt_cannot_enter_another_first_attempt(self):
        value = copy.deepcopy(self.payload)
        value['inventory']['receipts'] = [self.historical_receipt(current=True).model_dump(mode='json')]
        self.refused(value, 'PORTABLE_INPUT_ALREADY_RECEIPTED')

    def test_duplicate_receipt_identity_is_not_hidden_by_mapping_conversion(self):
        value = copy.deepcopy(self.payload)
        receipt = self.historical_receipt().model_dump(mode='json')
        value['inventory']['receipts'] = [receipt, copy.deepcopy(receipt)]
        self.refused(value, 'PORTABLE_INPUT_INVENTORY')

    def test_complete_older_receipt_content_is_committed_even_without_resource_change(self):
        from nonzero_cloudops.models.digest import compute_evidence_digest
        value = copy.deepcopy(self.payload)
        receipt = self.historical_receipt()
        value['inventory']['receipts'] = [receipt.model_dump(mode='json')]
        first = self.parse(value)
        changed = receipt.model_copy(update={'executed_at': receipt.executed_at - timedelta(seconds=1)})
        changed = changed.model_copy(update={'receipt_hash': compute_evidence_digest(changed.receipt_payload())})
        value['inventory']['receipts'] = [changed.model_dump(mode='json')]
        second = self.parse(value)
        self.assertNotEqual(first.state_root, second.state_root)
        self.assertNotEqual(first.receipts_root, second.receipts_root)
        self.assertEqual(first.resources_root, second.resources_root)

    def test_valid_ingress_proposal_is_explicitly_outside_the_first_release_profile(self):
        group = next(item for item in self.resources if isinstance(item, portable.SecurityGroupResource))
        class ReadOnlyGroup:
            adapter_name = 'private-owned-fixture'

            def get_resource(inner, query):
                return group

        evidence = QueryResource(ReadOnlyGroup()).execute(ResourceQuery(
            resource_type=group.resource_type, resource_id=group.resource_id, region=group.region),
            run=self.run, observed_at=self.now).value
        proposal = RemediationProposal.create(
            proposal_id=generate_proposal_id(), evidence=evidence,
            operation_type=RemediationOperation.REVOKE_PUBLIC_INGRESS,
            normalized_parameters={'security_group_id': group.resource_id,
                'ingress_rules': [item.model_dump(mode='json') for item in group.inbound_rules]},
            authority_class=AuthorityGate.PLAN_AND_CONFIRM,
            risk_summary='Owned fixture alternate operation', created_at=self.now,
            expires_at=self.proposal.expires_at,
        ).model_copy(update={'status': ProposalState.AWAITING_APPROVAL})
        request = LocalApprovalRequestRecord.create(
            request_id=generate_proposal_id(), proposal=proposal, actor_session_id='a' * 64,
            decision_nonce_hash='b' * 64, requested_at=self.now, expires_at=self.request.expires_at)
        value = copy.deepcopy(self.payload)
        value.update(proposal=proposal.model_dump(mode='json'), evidence=evidence.model_dump(mode='json'),
                     request=request.model_dump(mode='json'))
        self.refused(value, 'PORTABLE_INPUT_OPERATION_DENIED')


    def same_run_receipt_with_key(self, key):
        from nonzero_cloudops.models import LocalExecutionReceipt
        from nonzero_cloudops.models.digest import compute_evidence_digest
        value = self.historical_receipt(current=True).model_copy(update={'idempotency_key': key})
        value = value.model_copy(update={'receipt_hash': compute_evidence_digest(value.receipt_payload())})
        return LocalExecutionReceipt.model_validate(value.model_dump(mode='json'))

    def test_legacy_same_run_receipt_blocks_a_new_first_attempt_pack(self):
        value = copy.deepcopy(self.payload)
        receipt = self.same_run_receipt_with_key('local-exec:' + self.proposal.proposal_hash)
        value['inventory']['receipts'] = [receipt.model_dump(mode='json')]
        self.refused(value, 'PORTABLE_INPUT_ALREADY_RECEIPTED')

    def test_coherent_same_run_receipt_cannot_be_renamed_to_bypass_consumption(self):
        value = copy.deepcopy(self.payload)
        receipt = self.same_run_receipt_with_key('renamed-owned-history-' + self.proposal.proposal_hash)
        value['inventory']['receipts'] = [receipt.model_dump(mode='json')]
        self.refused(value, 'PORTABLE_INPUT_ALREADY_RECEIPTED')


    def test_legacy_receipt_for_a_different_run_does_not_block_a_new_exact_request(self):
        from nonzero_cloudops.models import LocalExecutionReceipt
        from nonzero_cloudops.models.digest import compute_evidence_digest
        old = self.historical_receipt().model_copy(update={
            'idempotency_key': 'local-exec:' + self.proposal.proposal_hash})
        old = old.model_copy(update={'receipt_hash': compute_evidence_digest(old.receipt_payload())})
        old = LocalExecutionReceipt.model_validate(old.model_dump(mode='json'))
        self.assertNotEqual(self.proposal.run_id, old.run_id)
        self.assertEqual(self.proposal.proposal_hash, old.proposal_hash)
        value = copy.deepcopy(self.payload)
        value['inventory']['receipts'] = [old.model_dump(mode='json')]
        parsed = self.parse(value)
        self.assertEqual('NONE', parsed.authority)
        self.assertEqual([old.model_dump(mode='json')], parsed.to_dict()['inventory']['receipts'])


if __name__ == '__main__':
    unittest.main()
