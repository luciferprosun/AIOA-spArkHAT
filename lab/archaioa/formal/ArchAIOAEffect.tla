-------------------------- MODULE ArchAIOAEffect --------------------------
EXTENDS Naturals
\* SPEC_ONLY / UNCHECKED_BY_TLC. Portable companion to effect_model.py.
\* One task, one warrant, one potential external effect. History witnesses
\* preserve authorization at dispatch/commit despite later invalidation.
VARIABLE s
vars == <<s>>
Init == s = [phase |-> "PROPOSED", warrant_present |-> FALSE,
  warrant_consumed |-> FALSE, warrant_current |-> TRUE,
  authority_attenuation_valid |-> TRUE, lease_epoch_current |-> TRUE,
  outcome |-> "NONE", open_liability_count |-> 0,
  reconciliation_evidence |-> FALSE, effect_count |-> 0, completed |-> FALSE,
  authorized_consumption |-> FALSE, dispatch_attenuation_valid |-> FALSE,
  dispatch_epoch_current |-> FALSE, commit_recorded |-> FALSE,
  commit_epoch_current |-> FALSE, unknown_seen |-> FALSE]

Verify == /\ s.phase = "PROPOSED"
          /\ s' = [s EXCEPT !.phase = "VERIFIED"]
RequireApproval == /\ s.phase = "VERIFIED"
                   /\ s' = [s EXCEPT !.phase = "APPROVAL_REQUIRED"]
GrantWarrant == /\ s.phase = "APPROVAL_REQUIRED" /\ ~s.warrant_present
                /\ s' = [s EXCEPT !.phase = "WARRANT_READY", !.warrant_present = TRUE]
RecordIntent == /\ s.phase = "WARRANT_READY"
                /\ s' = [s EXCEPT !.phase = "INTENT_RECORDED"]
InvalidationAllowed == s.phase \notin {"COMPLETED", "BLOCKED"}
InvalidateWarrant == /\ InvalidationAllowed /\ s.warrant_current
                     /\ s' = [s EXCEPT !.warrant_current = FALSE]
InvalidateAttenuation == /\ InvalidationAllowed /\ s.authority_attenuation_valid
                         /\ s' = [s EXCEPT !.authority_attenuation_valid = FALSE]
InvalidateEpoch == /\ InvalidationAllowed /\ s.lease_epoch_current
                   /\ s' = [s EXCEPT !.lease_epoch_current = FALSE]
Block == /\ s.phase \in {"PROPOSED", "VERIFIED", "APPROVAL_REQUIRED",
                         "WARRANT_READY", "INTENT_RECORDED"}
         /\ ~(s.warrant_current /\ s.authority_attenuation_valid /\ s.lease_epoch_current)
         /\ s' = [s EXCEPT !.phase = "BLOCKED"]
Dispatch == /\ s.phase = "INTENT_RECORDED"
            /\ s.warrant_present /\ ~s.warrant_consumed /\ s.warrant_current
            /\ s.authority_attenuation_valid /\ s.lease_epoch_current
            /\ s.effect_count = 0 /\ s.outcome = "NONE" /\ ~s.unknown_seen
            /\ s' = [s EXCEPT !.phase = "DISPATCHED", !.warrant_consumed = TRUE,
                      !.effect_count = 1, !.authorized_consumption = TRUE,
                      !.dispatch_attenuation_valid = TRUE, !.dispatch_epoch_current = TRUE]
Ack(result) == /\ s.phase = "DISPATCHED"
               /\ s' = [s EXCEPT !.phase = "ACKED", !.outcome = result]
LoseAck == /\ s.phase = "DISPATCHED"
           /\ s' = [s EXCEPT !.phase = "UNKNOWN", !.outcome = "UNKNOWN",
                     !.open_liability_count = 1, !.unknown_seen = TRUE]
Commit(result, target) == /\ s.phase = "ACKED" /\ s.outcome = result
                          /\ s.lease_epoch_current
                          /\ s' = [s EXCEPT !.phase = target, !.commit_recorded = TRUE,
                                    !.commit_epoch_current = TRUE]
BeginReconciliation == /\ s.phase = "UNKNOWN"
                       /\ s' = [s EXCEPT !.phase = "RECONCILING"]
RecordEvidence == /\ s.phase = "RECONCILING" /\ ~s.reconciliation_evidence
                  /\ s' = [s EXCEPT !.reconciliation_evidence = TRUE]
Resolve(result, target) == /\ s.phase = "RECONCILING" /\ s.outcome = "UNKNOWN"
                           /\ s.reconciliation_evidence /\ s.lease_epoch_current
                           /\ s' = [s EXCEPT !.phase = target, !.outcome = result,
                                     !.open_liability_count = 0, !.commit_recorded = TRUE,
                                     !.commit_epoch_current = TRUE]
Complete == /\ s.phase \in {"EXECUTED", "NOT_APPLIED"}
            /\ s.open_liability_count = 0 /\ s.outcome \in {"APPLIED", "NOT_APPLIED"}
            /\ (~s.unknown_seen \/ s.reconciliation_evidence)
            /\ s' = [s EXCEPT !.phase = "COMPLETED", !.completed = TRUE]

\* Next ordering corresponds to Python ACTIONS; Ack/Commit/Resolve each
\* have separate applied/not-applied labels in Python's deterministic graph.
Next == Verify \/ RequireApproval \/ GrantWarrant \/ RecordIntent
        \/ InvalidateWarrant \/ InvalidateAttenuation \/ InvalidateEpoch \/ Block
        \/ Dispatch \/ Ack("APPLIED") \/ Ack("NOT_APPLIED") \/ LoseAck
        \/ Commit("APPLIED", "EXECUTED") \/ Commit("NOT_APPLIED", "NOT_APPLIED")
        \/ BeginReconciliation \/ RecordEvidence
        \/ Resolve("APPLIED", "EXECUTED") \/ Resolve("NOT_APPLIED", "NOT_APPLIED")
        \/ Complete
Spec == Init /\ [][Next]_vars

NoEffectWithoutWarrant == s.effect_count > 0 =>
  (s.warrant_present /\ s.warrant_consumed /\ s.authorized_consumption)
NoWarrantReuse == s.effect_count <= 1
NoAuthorityAmplification == s.effect_count > 0 => s.dispatch_attenuation_valid
NoStaleEpochCommit == /\ (s.effect_count > 0 => s.dispatch_epoch_current)
                     /\ (s.commit_recorded => s.commit_epoch_current)
NoUnknownToSuccessWithoutEvidence ==
  (s.unknown_seen /\ s.phase \in {"EXECUTED", "NOT_APPLIED", "COMPLETED"}) =>
    (s.reconciliation_evidence /\ s.outcome \in {"APPLIED", "NOT_APPLIED"})
NoCompletedTaskWithOpenLiability == s.completed =>
  (s.open_liability_count = 0 /\ s.outcome # "UNKNOWN")
=============================================================================
