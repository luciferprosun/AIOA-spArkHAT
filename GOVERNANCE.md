# Governance

AIOA spArkHAT is an open-source project governed by maintainers with a human-approval-first operating model.

## Maintainer

The current repository maintainer and release authority is:

- [@luciferprosun](https://github.com/luciferprosun)

Additional maintainers may be added after sustained contribution, demonstrated review judgment, and explicit approval by the existing maintainer.

## Decision making

Project decisions are made through reviewable artifacts:

1. issues or documented proposals for material changes;
2. pull requests for implementation;
3. tests and reproducible evidence for behavior changes;
4. maintainer review before merge;
5. ADRs or governance documentation when a decision changes an architectural or authority boundary.

Small fixes may be accepted directly by maintainer review. Changes to security, authority, evidence, provenance, replay behavior, credential handling, or external effects require explicit review and test evidence.

## Human authority

AI tools and coding agents may propose code, tests, documentation, or review findings, but they do not have independent project authority. They cannot self-approve protected changes, merge themselves, grant credentials, or authorize external effects.

## Contribution path

Contributors are welcome to:

- open issues with reproducible evidence;
- propose documentation or tests;
- submit focused pull requests;
- participate in review and threat-model discussions.

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

Potential vulnerabilities must be reported privately through GitHub Private Vulnerability Reporting. See [SECURITY.md](SECURITY.md).

## Releases

Release tags are created by the maintainer after review of tests, provenance, licensing, and release-specific evidence. Historical competition branches and archived material are retained for reproducibility and are not equivalent to current release authority.

## Governance records

Runtime governance invariants and implementation status are additionally documented under:

- `governance/`
- `docs/governance/`
- `AUTHORITY_SCOPE.md`
- `PROVENANCE_FOUNDATION.md`

When these materials conflict, the current default-branch documentation and tested runtime behavior take precedence.
