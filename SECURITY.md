# Security Policy

AIOA spArkHAT is a local-first AI-agent runtime with explicit authority, approval, provenance, and replay-safety boundaries. Security reports are welcome.

## Supported code

Security fixes target the current `main` branch and the latest tagged release. Historical, archive, checkpoint, and competition branches are preserved for reproducibility and are not independently supported unless a fix is required to protect users of the current runtime.

## Reporting a vulnerability

Please **do not open a public issue** for a suspected vulnerability.

Use GitHub's **Private Vulnerability Reporting / Security Advisory** flow for this repository so details can be reviewed privately with the maintainer.

Useful reports include:

- affected commit or release;
- reproducible steps or a minimal proof of concept;
- impact and expected security boundary;
- whether secrets, credentials, tool execution, approval, provenance, replay safety, or browser/action containment are involved;
- suggested mitigation, if known.

The maintainer will acknowledge credible reports as soon as practical, coordinate remediation, and publish a security advisory when appropriate.

## High-priority security boundaries

Reports are especially valuable when they involve:

- bypass of human approval or authority checks;
- duplicate or replayed external effects;
- secret or credential exposure;
- command, filesystem, browser, or network boundary escape;
- provenance or evidence tampering;
- unauthorized provider output promotion;
- dependency or supply-chain compromise;
- unsafe behavior in the optional NonZero CloudOps module.

## Disclosure

Please allow reasonable time for investigation and remediation before public disclosure. Good-faith security research and responsible disclosure are appreciated.

## Secrets

Never include real API keys, passwords, tokens, private data, or production credentials in an issue, pull request, test fixture, or reproduction artifact.
