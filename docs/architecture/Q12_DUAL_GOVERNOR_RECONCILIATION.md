# Kill-active delayed receipt accounting

CoreDualGovernor retains the existing dual money/risk reservation and circuit protocol. A killed Core accepts delayed forward-clock accounting through mark_unknown, settle and release_not_dispatched. These operations cannot dispatch work. The durable kill flag, principal admission, current epoch, evidence binding, one-use markers and positive no-dispatch proof remain required. Clock rollback remains denied. A successful accounting transaction advances last_now monotonically.

New reservations, dispatch and unkill use the existing bounded clock guard. An unkill remains an explicit Core operator action. UNKNOWN and COMMITTED keep their full reserved money/risk exposure; only a durable no-dispatch marker releases exposure. UNKNOWN settlement does not count as circuit recovery or Verified Delta.

This is local fixture evidence. The four shared-audit integration fixtures require localhost access unavailable in this sandbox, so G7 acceptance remains blocked. No measured cost per Verified Delta, LIVE credits or production storage guarantee is asserted.
