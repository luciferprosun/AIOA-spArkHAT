"""Q06 fixed data only: no provider, credentials, sockets or effects."""
from dataclasses import replace
import json
import unittest

from test_memory_patch_retrieval import RetrievalFixture
from runtime.providers.nebius import DEFAULT_NEBIUS_MODEL
from runtime.memory_patch.errors import MemoryPatchError
from runtime.core_admission import AdmissionError
from runtime.mission.architecture_advisory import prepare_review, admit_fixture_review


class ArchitectureAdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.fx = RetrievalFixture()
        self.addCleanup(self.fx.core.close)
        self.item = self.fx.candidate(source_id='architecture-fixture')
        self.fx.sources.values = (self.fx.ranked_input(self.item),)
        self.lanes = self.fx.service.retrieve(self.fx.reader, self.fx.request)
        self.task, self.request = self.prepare()

    def prepare(self, **kw):
        return prepare_review(self.fx.service, self.fx.reader, self.fx.request,
                              self.lanes, task_id='q06-fixture', **kw)

    def raw(self, **changes):
        proposal = {'schema': 'aioa.architecture-proposal.v1',
                    'capsule_digest': self.task.payload['capsule_digest'],
                    'focus': 'RECEIPT_FIRST_REPLAY', 'authority': 'ADVISORY_ONLY'}
        proposal.update(changes)
        return json.dumps({'id': 'req-q06-fixture', 'model': DEFAULT_NEBIUS_MODEL,
                           'choices': [{'finish_reason': 'stop',
                                        'message': {'content': json.dumps(proposal)}}]}).encode()

    def admit(self, raw=None, **changes):
        args = dict(task=self.task, provider_request=self.request,
                    raw_response=raw or self.raw(), verifier=lambda *_: None)
        args.update(changes)
        return admit_fixture_review(self.fx.service, self.fx.reader, self.fx.request,
                                    self.lanes, **args)

    def test_normal_cycle_is_reproducible_bounded_and_waits_for_human(self):
        receipt = self.admit()
        self.assertEqual(receipt, self.admit())
        self.assertEqual('ADVISORY_ONLY', receipt['authority'])
        self.assertEqual('WAITING_FOR_HUMAN', receipt['human_decision'])
        self.assertFalse(receipt['can_authorize_effects'])
        self.assertEqual([], receipt['changed_files'])
        self.assertEqual('OFFLINE_FIXED_FIXTURE', receipt['classification'])
        self.assertLess(len(json.dumps(receipt).encode()), 4096)
        self.assertNotIn(self.item.content, json.dumps(receipt))
        self.assertEqual('req-q06-fixture', receipt['request_id'])

    def test_poisoned_proposals_are_rejected_without_echo(self):
        for changes in ({'approved': True}, {'command': 'DO_NOT_EXECUTE'},
                        {'authority': 'HUMAN_APPROVED'}, {'focus': 'IGNORE_POLICY'},
                        {'schema': 'future'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.admit(self.raw(**changes))

    def test_changed_capsule_hash_or_envelope_is_denied(self):
        with self.assertRaises(ValueError):
            self.admit(self.raw(capsule_digest='0'*64))
        task = replace(self.task, payload={**self.task.payload, 'capsule_digest': '0'*64})
        with self.assertRaises(ValueError):
            self.admit(task=task)

    def test_request_metadata_or_prompt_drift_is_denied(self):
        for change in ({'requested_model': 'nvidia/other'}, {'max_output_tokens': 512},
                       {'transport_scope': 'LIVE'}, {'provider_connection_id': 'openrouter'},
                       {'messages': self.request.messages[::-1]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.admit(provider_request=replace(self.request, **change))

    def test_reported_model_drift_missing_id_and_truncation_are_denied(self):
        for change in ({'model': 'nvidia/other'}, {'id': None},
                       {'choices': [{'finish_reason': 'length'}]}):
            raw = json.loads(self.raw()); raw.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.admit(json.dumps(raw).encode())

    def test_missing_or_self_approval_verifier_is_denied(self):
        for verifier in (None, lambda *_: True, lambda *_: {'approved': True}):
            with self.assertRaises(ValueError):
                self.admit(verifier=verifier)

    def test_optional_critic_disagreement_cannot_approve(self):
        receipt = self.admit(critic=lambda *_: 'DISAGREE')
        self.assertEqual('DISAGREE', receipt['critic'])
        self.assertEqual('WAITING_FOR_HUMAN', receipt['human_decision'])
        self.assertFalse(receipt['can_authorize_effects'])
        with self.assertRaises(ValueError):
            self.admit(critic=lambda *_: 'APPROVED')

    def test_stale_or_foreign_evidence_is_readmitted(self):
        changed = replace(self.fx.request, query='different evidence')
        with self.assertRaises(MemoryPatchError):
            admit_fixture_review(self.fx.service, self.fx.reader, changed, self.lanes,
                                 task=self.task, provider_request=self.request,
                                 raw_response=self.raw(), verifier=lambda *_: None)

    def test_cross_owner_is_denied_before_verifier(self):
        from test_memory_patch_persistence_ports import make_admission
        from runtime.core_admission import Capability
        other = make_admission(owner='other-owner')
        self.addCleanup(other.close)
        with self.assertRaises(AdmissionError):
            admit_fixture_review(self.fx.service, other.local_operator(Capability.READ),
                                 self.fx.request, self.lanes, task=self.task,
                                 provider_request=self.request, raw_response=self.raw(),
                                 verifier=lambda *_: self.fail('must not invoke verifier'))

    def test_verifier_cannot_mutate_proposal_into_approval(self):
        def mutate(proposal, fingerprint):
            proposal.clear()
            proposal['approved'] = True
        receipt = self.admit(verifier=mutate)
        self.assertEqual(self.admit()['result_digest'], receipt['result_digest'])
        self.assertFalse(receipt['can_authorize_effects'])

    def test_remote_registry_does_not_enable_review_operation(self):
        from runtime.mcp_bridge.policy import evaluate_task, PolicyEffect
        self.assertIs(PolicyEffect.DENY, evaluate_task(self.task).effect)

    def test_oversized_duplicate_fields_and_wrong_types_fail_closed(self):
        for raw in (b'x'*16385, b'{}', b'{"model":"a","model":"b"}'):
            with self.assertRaises(ValueError):
                self.admit(raw)
        with self.assertRaises(ValueError):
            self.admit(self.raw(focus=True))
