# NV08 test matrix

All local rows run without network access.  The durable file adapter is a
contract fixture and is never counted as Cockroach evidence.

| Mandate case | Local evidence | Live evidence in this run |
| --- | --- | --- |
| Two-user isolation under read/cache/export/score/log | `test_nv08_index.test_two_owner_shared_store_has_no_read_score_log_or_index_leak`; inherited `test_nv07_chat.test_concurrent_users_share_store_without_read_cache_score_or_log_leak`, `test_memory_patch_retrieval.test_cache_is_explicit_and_owner_bound`, and owner-only export tests | NOT_RUN — requires permitted Cockroach profile |
| Same replay does not duplicate delta/reward/index | `test_replay_creates_no_second_delta_reward_or_index_artifact` and concurrent exact replay tests | NOT_RUN |
| Revoked/stale source cannot regain eligibility from score | `test_high_score_cannot_revive_stale_or_unknown_delta`; inherited temporal/revocation tests | NOT_RUN |
| Indexed form retains conditions and verification metadata | `test_index_retains_condition_and_verification_but_changes_no_actual_order` | Not backend-specific |
| Fresh-process durable retrieval | `test_fresh_process_rebuilds_equivalent_index_and_context`; `nv08_measure.py` | NOT_RUN |
| Crash before commit | inherited `test_domain_mutation_audit_outbox_are_atomic` and rollback tests | NOT_RUN |
| Crash/unknown after commit | inherited `test_unknown_commit_requires_read_only_reconciliation` and `test_unknown_native_learning_commit_blocks_further_automatic_work` | NOT_RUN |
| Crash after effect marker | inherited pending-outbox/publication replay tests; no index effect marker exists because the index is derived and SHADOW-only | NOT_RUN |
| Concurrent dedup | `test_concurrent_same_submission_is_one_delta_event_and_index_entry`; inherited `test_concurrent_exact_replay` | NOT_RUN |
| Pool reconnect/reset | Cockroach pool reset/reconnect contract remains covered structurally; fixture is not promoted to live evidence | BLOCKED_EXTERNAL |
| Non-admin role cannot access another tenant | FORCE RLS/application-role SQL contracts and manifest checks remain in the suite | BLOCKED_EXTERNAL |
| Fixture and live evidence separated | NV08 docs, measurement schema and acceptance JSON label the file adapter `NOT_COCKROACH`; live gate is independent | `G08_DB_LIVE=BLOCKED_EXTERNAL` |

The compact index is capped at 32 entries and scans at most 16 candidates.  It
is fixed to SHADOW; attempting ACTIVE construction is a contract failure.  The
actual NV05 DVM order is asserted unchanged.
