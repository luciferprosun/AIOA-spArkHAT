# Hackathon prior-art disclosure

## Disclosure

AIOA/AOIA and Non-Zero existed before the AWS Agents for Humans Hackathon as independent research
and prior projects. This hackathon repository reuses high-level concepts such as model output not
being authority, propose–gate–execute, typed state, human approval, provenance, idempotency,
checkpoint recovery, and fail-closed behavior.

The canonical disclosure states that no implementation code, commit, migration, deployment
definition, or generated asset from those earlier projects was imported. The implementation in this
repository was newly authored for the hackathon unless a later disclosed exception is added. No such
exception appears in the reviewed history.

## Repository-grounded provenance

- `d813290727b89017bd348c04f68a7f07156652f7` initialized the clean-room repository on 2026-08-22
  and added both the MIT License and the root prior-art disclosure.
- `a6786459405d0071ef802abb1535211c13435136` added the initial Strands/Bedrock integration on
  2026-08-23.
- `e8a2864778437a8b253e14efd247df4da70fa30f` added verified sandbox remediation on 2026-08-23.
- `151affc1b731308e7cad2b96f96f1b0b77d39fe5` added restart-safe recovery and reconciliation on
  2026-08-24.
- `b5dba16a9af1bc979b2b96a50ddbf0e590e829a5` began the credential-free Local-First path on
  2026-08-26.
- `d18f945a1484a1255339a3b4bcb1560c58d06d9b` hardened the portable container on 2026-09-01.
- `dbea5411b1c0d81de0035d9ef08e28211fb79e79` certified the clean-clone container judge flow on
  2026-09-01.

Dates above are commit dates from this repository. They are not claims about the creation dates of
the separate prior projects. The history supports evolution of this clean-room repository; it does
not establish ownership or licensing of unrelated work.

## License

The exact MIT text in `LICENSE` has been present since the initial repository commit. B6 preserves
it verbatim. No new license was invented and no legal conclusion beyond the repository's explicit
license is asserted.

## Publication rule

Publish this disclosure with the source package. If any imported implementation or asset is later
identified, stop publication and add its precise source, license, authorship, date, and modifications
before making a new claim.
