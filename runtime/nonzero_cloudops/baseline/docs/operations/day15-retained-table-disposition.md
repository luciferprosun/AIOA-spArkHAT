# Day 15 retained state-table disposition

The Day 15 DynamoDB table is durable evidence, not disposable stack scaffolding. The template uses
on-demand billing, encryption, point-in-time recovery, deletion protection,
`DeletionPolicy: Retain`, and `UpdateReplacePolicy: Retain`.

Stack rollback, replacement, alias rollback, and ordinary teardown must not delete the table. The
deployment and alias tools contain no table-delete operation. A retained table may continue to
incur storage and backup cost after the stack is removed.

Before any separately authorized destructive disposition, an operator must:

1. identify the retained physical table without placing its identifier in public evidence;
2. confirm retention ownership and the required legal/audit period;
3. export or back up the required records and independently verify recoverability;
4. record approval for the exact table and account in a private operational system;
5. remove deletion protection only as a separately reviewed change; and
6. issue any deletion as a separate explicit operation outside the Day 15 gate and rollback tools.

A missing owner, unverified backup, ambiguous table identity, or absent authorization stops the
process. This runbook does not authorize removal and intentionally provides no deletion command.
