# Dependency / license / rights inventory — local candidate

Candidate: e7a0a747e2e9fea8f75416ec6d6d3a35a5152ae0

Locally established:
- changed-file secret scanner remains unchanged and passed the accepted day-shift candidate;
- no broad allowlist or history rewrite was used;
- historical classifications remain 75 FIXTURE, 5 EXAMPLE_PLACEHOLDER, 26 NON_CREDENTIAL_IDENTIFIER.

Human gates still open:
- complete transitive license/notices review;
- clean pinned-install reproducibility proof;
- bundled PDF/media redistribution rights;
- model/service terms, eligibility and IP attestations;
- 30 historical fixture observations without independently established synthetic provenance;
- 10 historical binary objects are now path/type inventoried; embedded-content and redistribution-rights review remains human-gated.

Status: PARTIAL_WITH_DOCUMENTED_HUMAN_GATES.

## Direct dependency declarations
- Build: setuptools>=65, wheel
- Optional Non-Zero: pydantic==2.13.4, uuid6==2025.0.1
- Optional Cockroach: psycopg[binary]==3.3.5
- Runtime requirements: google-genai>=1.0.0, playwright>=1.59.0, beautifulsoup4>=4.12.0, rich>=13.7.0, textual>=0.86.0

See HISTORICAL_BINARY_BLOB_INVENTORY.md for the ten historical binary objects.
