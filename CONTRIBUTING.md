# Contributing to AIOA spArkHAT

Thank you for helping improve AIOA spArkHAT.

## Before starting

For significant changes, open an issue or discussion first so scope, safety boundaries, and test expectations can be agreed before implementation.

Security vulnerabilities must **not** be filed publicly. Use the private reporting process described in [SECURITY.md](SECURITY.md).

## Development setup

Requirements:

- Python 3.11 or newer
- Git

Create an isolated environment and install the Core plus optional NonZero dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install '.[nonzero]'
```

Optional CockroachDB support:

```bash
python -m pip install '.[cockroach]'
```

## Tests

Before opening a pull request, run the relevant tests. The CI workflow validates Python 3.11 and 3.12.

A broad local test command is:

```bash
python -m unittest discover -s tests -p 'test*.py'
```

The NVIDIA reviewer preflight is deterministic and requires no API key:

```bash
python -I -B scripts/nvidia_reviewer_preflight.py
```

If you modify the native NonZero integration, also run its dedicated tests and architecture checks documented in the repository CI workflow.

## Pull requests

Keep pull requests focused. Include:

- what changed and why;
- affected security or authority boundaries;
- tests executed and results;
- any migration or compatibility impact;
- screenshots or reproducible evidence for UI/runtime behavior when relevant.

Do not commit credentials, tokens, private datasets, production logs, or generated secret material.

## Safety-critical changes

Changes affecting external actions, human approval, evidence promotion, provenance, replay protection, credential handling, or execution containment require explicit maintainer review and regression tests.

## AI-assisted contributions

AI tools may assist with implementation and review, but contributors remain responsible for verifying the code, tests, claims, and licensing of submitted work.
